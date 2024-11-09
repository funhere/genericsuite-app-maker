"""
codegen_schema_generator.py
2024-10-27 | CR
"""
# from typing import Any
import os
import sys
import time
from datetime import datetime

import json
import pprint

import argparse

from lib.codegen_ai_utilities import LlmProvider
from lib.codegen_utilities import (
    get_default_resultset,
    read_file,
)
from lib.codegen_utilities import get_app_config
# from lib.codegen_utilities import log_debug

DEBUG = True
USE_PPRINT = False

DEFAULT_AI_PROVIDER = [
    "chat_openai",
    "groq",
    "ollama",
    "rhymes",
    "nvidia",
]

DEFAULT_MODEL_TO_USE = {
    "chat_openai": "gpt-4-mini",
    "groq": "llama3-8b-8192",
    "ollama": "llama3.2",
              # "llava",
              # "deepseek-coder-v2",
              # "nemotron",
    "rhymes": "aria",
    "nvidia": "nvidia/llama-3.1-nemotron-70b-instruct",
}

DEFAULT_TEMPERATURE = "0.5"
DEFAULT_STREAM = ""

DEFAULT_AGENTS_COUNT = 0

OLLAMA_BASE_URL = ""
# OLLAMA_BASE_URL = "localhost:11434"


# Default prompt to generate the .json files for the frontend and backend
DEFAULT_PROMPT = """
You are a developer specialized in JSON files generation and
Python Langchain Tools implementation.
Your task is to create the JSON files for the frontend and backend
of the given application and the Langchain Tools to perform the search,
insert and update operations.
"""
USER_MESSAGE_PROMPT = """
The given application and its schema/table descriptions are described below:
----------------
{user_input}
----------------
Based on the following documentation and examples:
{files}
Give me the generic CRUD editor configuration JSON files for
the given application, and the python code to implement the Langchain Tools
to perform the search, insert and update operations for the given application
tables.
The JSON files must be build according to the specs and instructions
in the `Generic-CRUD-Editor-Configuration.md` file.
The example files: `frontend/users.json`, `frontend/users_config.json`,
`backend/users.json`, and `backend/users_config.json` are included only as
a reference for you to know how to build the JSON files.
The Python files: `ai_gpt_fn_index.py` and `ai_gpt_fn_tables.py`
are included as a reference for you to know how to implement the
Langchain Tools.
Don't give recommendations, observations, or explanations about the database,
just give me the names and content of JSON files (not the JSON example files)
for the given application and the Langchain Tools python code.
"""


class ArgsClass:
    def __init__(self, params: dict):
        params = params or {}

        def get_param_or_envvar(param_name: str, default_value: str = None):
            return params.get(
                param_name,
                os.environ.get(
                    "LLM_PROVIDER",
                    default_value)
            )

        self.user_input_text = params.get("user_input_text")
        self.user_input_file = params.get("user_input_file")
        self.provider = params.get(
            "provider",
            get_param_or_envvar("LLM_PROVIDER", DEFAULT_AI_PROVIDER[0]))
        self.model = params.get("model")
        # self.model = params.get(
        #     "model",
        #     DEFAULT_MODEL_TO_USE[DEFAULT_AI_PROVIDER[0]])
        self.temperature = params.get("temperature", DEFAULT_TEMPERATURE)
        self.stream = params.get("stream", DEFAULT_STREAM)
        self.ollama_base_url = params.get("ollama_base_url", OLLAMA_BASE_URL)
        self.agents_count = params.get("agents_count", DEFAULT_AGENTS_COUNT)


class JsonGenerator:
    """
    Class to generate the .json files for the frontend and backend
    """

    def __init__(self, params: dict = None):
        if not params:
            params = {}
        self.params = params or {}
        self.args = self.read_arguments(params)
        self.args.update(get_app_config())
        self.reference_files = self.get_reference_files()
        self.prompt = DEFAULT_PROMPT
        self.user_input = self.get_user_input()
        self.final_input = None
        self.final_summary = None
        self.provider_model_used = None
        self.model_config = {}

    def read_arguments(self, params):
        """
        Decide where to read arguments from
        """
        if len(sys.argv) > 1:
            # If it's called from the command line, we need to read the
            # arguments from the command line
            args = self.read_arguments_from_cli()
        else:
            # If it's not called from the command line, we need to read the
            # arguments from the environment variables
            args = ArgsClass(params)
        return args

    def read_arguments_from_cli(self):
        """
        Read arguments from the command line
        """
        parser = argparse.ArgumentParser()
        parser.add_argument(
            '--user_input_text',
            type=str,
            default=None,
            help='User input text to be used as the initial plan. ' +
                 'It\'s mandatory to provide a user input file or text.'
        )
        parser.add_argument(
            '--user_input_file',
            type=str,
            default=None,
            help='User input file to be used as the initial plan. ' +
                 'It\'s mandatory to provide a user input file or text.'
        )
        parser.add_argument(
            '--provider',
            type=str,
            default=DEFAULT_AI_PROVIDER[0],
            help='Provider to use (ollama, nvidia, chat_openai, groq). ' +
            f'Default: {DEFAULT_AI_PROVIDER[0]}'
        )
        parser.add_argument(
            '--model',
            type=str,
            default=DEFAULT_MODEL_TO_USE[DEFAULT_AI_PROVIDER[0]],
            help='Model to use. Default: ' +
                 DEFAULT_MODEL_TO_USE[DEFAULT_AI_PROVIDER[0]]
        )
        parser.add_argument(
            '--temperature',
            type=str,
            default=DEFAULT_TEMPERATURE,
            help=f'Temperature to use. Default: {0.5}'
        )
        parser.add_argument(
            '--stream',
            type=str,
            default=DEFAULT_STREAM,
            help=f'Stream to use. Default: {"1"}'
        )
        parser.add_argument(
            '--agents_count',
            type=int,
            default=DEFAULT_AGENTS_COUNT,
            help=f'Number of agents to use. Default: {DEFAULT_AGENTS_COUNT}'
        )
        parser.add_argument(
            '--ollama_base_url',
            type=str,
            default=OLLAMA_BASE_URL,
            help=f'Ollama base URL. Default: {OLLAMA_BASE_URL}'
        )

        args = parser.parse_args()
        return args

    def read_user_input(self):
        """
        Read the user input from a file
        """
        if self.args.user_input is None:
            raise ValueError("User input file is mandatory")

        if not os.path.exists(self.args.user_input):
            raise FileNotFoundError(
                f"User input file not found: {self.args.user_input}")

        with open(self.args.user_input, 'r') as f:
            user_input = f.read()

        return user_input

    def get_user_input(self):
        """
        Returns the user input text or file
        """
        if self.args.user_input_file:
            user_input = self.read_user_input_file()
        else:
            user_input = self.args.user_input_text
        user_input = USER_MESSAGE_PROMPT.format(
            user_input=user_input,
            files="\n".join([
                f"\nFile: {f.get('name')}" +
                "\nFile content:" +
                "\n-----------------" +
                f"\n{f.get('content')}" +
                "\n-----------------"
                for f in self.reference_files
            ]),
        )
        return user_input

    def log_debug(self, message):
        """
        Prints the message for debugging
        """
        if DEBUG:
            print(message)

    def log_debug_structured(self, messages):
        """
        Prints the messages in a structured way for debugging
        """
        if DEBUG:
            if USE_PPRINT:
                pp = pprint.PrettyPrinter(indent=4)
                pp.pprint(messages)
                print("")
            else:
                print(messages)

    def get_elapsed_time_formatted(self, elapsed_time):
        """
        Returns the elapsed time formatted
        """
        if elapsed_time < 60:
            return f"{elapsed_time:.2f} seconds"
        elif elapsed_time < 3600:
            return f"{elapsed_time / 60:.2f} minutes"
        else:
            return f"{elapsed_time / 3600:.2f} hours"

    def log_procesing_time(self, message: str = "", start_time: float = None):
        """
        Returns the current time and prints the message
        """
        if start_time is None:
            start_time = time.time()
            readable_timestamp = datetime.fromtimestamp(start_time) \
                .strftime('%Y-%m-%d %H:%M:%S')
            print("")
            print((message if message else 'Process') +
                  f" started at {readable_timestamp}...")
            return start_time

        end_time = time.time()

        readable_timestamp = datetime.fromtimestamp(end_time) \
            .strftime('%Y-%m-%d %H:%M:%S')
        processing_time = self.get_elapsed_time_formatted(
            end_time - start_time)

        print("")
        print(
            (message if message else 'Process') +
            f" ended at {readable_timestamp}" +
            f". Processing time: {processing_time}")
        return end_time

    def get_model(self, model_to_use: str = None):
        """
        Returns the model to use based on the default model to use
        """
        if not model_to_use:
            model_to_use = self.args.model
        return model_to_use

    # def unify_messages(self, messages):
    #     """
    #     Unifies the messages to be compatible with the different providers
    #     """
    #     # Both system and user must be unified in one user message
    #     return [{
    #         "role": "user",
    #         "content": "\n".join([m["content"] for m in messages])
    #     }]

    # def fix_messages(self, messages):
    #     """
    #     Fixes the messages to be compatible with the different providers
    #     """
    #     if self.args.provider == "nvidia":
    #         return self.unify_messages(messages)
    #     return messages

    # def get_openai_api_response(self, response_raw: Any) -> str:
    #     """
    #     Returns the response from the OpenAI API
    #     """
    #     if self.model_config.get('stream', False):
    #         response = ""
    #         for chunk in response_raw:
    #             if chunk.choices[0].delta.content is not None:
    #                 print(chunk.choices[0].delta.content, end="")
    #                 response += chunk.choices[0].delta.content
    #     else:
    #         response = response_raw.choices[0].message.content
    #     return response

    # def get_model_response(self, model: str, messages: list):
    #     """
    #     Returns the response from the model
    #     """
    #     self.model_config = {
    #         'messages': self.fix_messages(messages),
    #         'model': model,
    #     }

    #     if self.args.temperature:
    #         if self.args.provider == "ollama":
    #             self.model_config['options'] = {
    #                 "temperature": float(self.args.temperature)
    #             }
    #         else:
    #             self.model_config['temperature'] = \
    #                 float(self.args.temperature)
    #     elif self.args.provider == "nvidia":
    #         self.model_config['temperature'] = 0.5

    #     if self.args.stream:
    #         self.model_config['stream'] = self.args.stream == "1"
    #     if self.args.provider == "nvidia":
    #         self.model_config['stream'] = True

    #     # Reference:
    #     # https://pypi.org/project/ollama/
    #     # https://github.com/ollama/ollama/blob/main/docs/api.md
    #     #
    #     self.provider_model_used = \
    #         f"Provider: {self.args.provider}" + \
    #         f" | Model: {self.model_config['model']}"
    #     self.log_debug("")
    #     self.log_debug(self.provider_model_used)
    #     # self.log_debug_structured(self.model_config)

    #     if self.args.provider == "ollama":
    #         if self.args.ollama_base_url:
    #             self.log_debug(
    #                 "Using ollama client with base_url:" +
    #                 f" {self.args.ollama_base_url}")
    #             self.log_debug("")
    #             client = Client(host=self.args.ollama_base_url)
    #             response_raw = client.chat(**self.model_config)
    #         else:
    #             response_raw = ollama.chat(**self.model_config)
    #         response = response_raw['message']['content']

    #     elif self.args.provider == "groq":
    #         client = Groq(
    #             api_key=os.environ.get("GROQ_API_KEY"),
    #         )
    #         response_raw = client.chat.completions.create(
    #             **self.model_config)
    #         response = response_raw.choices[0].message.content

    #     elif self.args.provider == "nvidia":
    #         # Reference:
    #         # https://build.nvidia.com/nvidia/llama-3_1-nemotron-70b-instruct
    #         client = OpenAI(
    #             base_url="https://integrate.api.nvidia.com/v1",
    #             api_key=os.environ.get("NVIDIA_API_KEY"),
    #         )
    #         response_raw = client.chat.completions.create(
    #             top_p=1,
    #             # max_tokens=1024,
    #             **self.model_config)
    #         response = self.get_openai_api_response(response_raw)

    #     elif self.args.provider == "rhymes":
    #         # Reference:
    #         # https://lablab.ai/t/aria-api-tutorial
    #         client = OpenAI(
    #             base_url='https://api.rhymes.ai/v1',
    #             api_key=os.environ.get("RHYMES_ARIA_API_KEY"),
    #         )
    #         response_raw = client.chat.completions.create(
    #             stop=["<|im_end|>"],
    #             top_p=1,
    #             # max_tokens=1024,
    #             **self.model_config)
    #         response = self.get_openai_api_response(response_raw)

    #     elif self.args.provider == "chat_openai" \
    #             or self.args.provider == "openai":
    #         client = OpenAI(
    #             api_key=os.environ.get("OPENAI_API_KEY"),
    #         )
    #         response_raw = client.chat.completions.create(
    #             top_p=1,
    #             **self.model_config)
    #         response = self.get_openai_api_response(response_raw)

    #     else:
    #         raise ValueError(f"Invalid provider: {self.args.provider}")

    #     # Model response debugging
    #     # self.log_debug("")
    #     # self.log_debug(f'Response: {response}')
    #     return response

    def get_model_response(self, model: str, prompt: str, user_input: str):
        """
        Returns the response from the model
        """
        self.model_config = {
            'model': model,
            "provider": self.args.provider,
            "temperature": self.args.temperature,
            "stream": self.args.stream,
            "ollama_base_url": self.args.ollama_base_url,
        }
        no_system_prompt = (self.args.provider in ["nvidia"])
        self.provider_model_used = \
            f"Provider: {self.args.provider}" + \
            f" | Model: {self.model_config['model']}"
        # self.log_debug_structured(self.model_config)
        llm_model = LlmProvider(self.model_config)
        llm_response = llm_model.query(
            prompt=prompt,
            question=user_input,
            unified=no_system_prompt,
        )
        if llm_response['error']:
            raise ValueError(f'ERROR: {llm_response["error_message"]}')
        return llm_response['response']

    def CEO_Agent(self, user_input, is_final=False):
        """
        Main agent that creates initial plan and final summary
        """
        system_prompt = 'You are o1, an AI assistant focused on clear ' + \
            'step-by-step reasoning. Break every task into ' + \
            f'{self.args.agents_count} actionable step(s). ' + \
            'Always answer in short.' \
            if not is_final else \
            'Summarize the following plan and its implementation into a ' + \
            'cohesive final strategy.'

        # messages = [
        #     {
        #         'role': 'system',
        #         'content': system_prompt
        #     },
        #     {
        #         'role': 'user',
        #         'content': user_input
        #     }
        # ]

        self.log_debug("")
        self.log_debug(f"CEO messages (is_final: {is_final}):")
        # self.log_debug_structured(messages)

        start_time = self.log_procesing_time(
            f'CEO {"final" if is_final else "initial"} processing...')

        response = self.get_model_response(
            model=self.get_model(),
            prompt=system_prompt,
            user_input=user_input,
            # messages=messages
        )

        self.log_procesing_time(start_time=start_time)
        self.log_debug("")
        self.log_debug(f'CEO {"final" if is_final else "initial"} response:')
        self.log_debug(response)

        return response

    def create_agent(self, step_number):
        """
        Factory method to create specialized agents for each step
        """
        def agent(task):
            # messages = [
            #     {
            #       'role': 'system',
            #       'content': f'You are Agent {step_number}, focused ONLY ' +
            #       f'on implementing step {step_number}. Provide a detailed' +
            #       ' but concise implementation of this specific step. ' +
            #       'Ignore all other steps.'
            #     },
            #     {
            #         'role': 'user',
            #         'content': f'Given this task:\n{task}\n\nProvide ' +
            #         f'implementation for step {step_number} only'
            #     }
            # ]
            system_prompt = (
                f'You are Agent {step_number}, focused ONLY ' +
                f'on implementing step {step_number}. Provide a detailed' +
                ' but concise implementation of this specific step. ' +
                'Ignore all other steps.'
            )
            user_input = (
                    f'Given this task:\n{task}\n\nProvide ' +
                    f'implementation for step {step_number} only'
            )
            self.log_debug("")
            self.log_debug(f'Agent step-{step_number} messages:')
            # self.log_debug_structured(messages)

            start_time = self.log_procesing_time(f"Agent step-{step_number}")
            response = self.get_model_response(
                model=self.get_model(),
                prompt=system_prompt,
                user_input=user_input,
                # messages=messages
            )

            self.log_procesing_time(
                message=f"Agent step-{step_number}",
                start_time=start_time)
            self.log_debug("")
            self.log_debug(f'Agent step-{step_number} response:')
            self.log_debug(response)

            return response

        return agent

    def get_reference_files(self):
        """
        Returns the reference files to be used
        """
        # Read the `schema_generator_ref_files.json` file
        with open('./config/schema_generator_ref_files.json', 'r') as f:
            ref_files = json.load(f)

        # Create a list of dictionaries with the name, path and content of each
        # reference file
        ref_files_list = [
            {
                'name': ref_file['name'],
                'path': ref_file['path'],
                'content': read_file(ref_file['path']),
            } for ref_file in ref_files
        ]
        return ref_files_list

    def save_result(self):
        """
        Saves the final result to a file
        """
        output_file = os.path.join(
            self.params.get('output_dir', "./output"),
            self.params.get('output_file', (
                'final_summary_{date_time}.txt'.format(
                    date_time=datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))))
        )
        with open(output_file, 'w') as f:
            if DEBUG:
                f.write("DEBUG Prompt:\n")
                f.write("\n")
                f.write(self.prompt)
                f.write("\n")
            f.write("\n")
            f.write("User input:\n")
            f.write("\n")
            f.write(self.user_input)
            f.write("\n")
            if self.final_input:
                f.write("\n")
                f.write("Final input:\n")
                f.write("\n")
                f.write(self.final_input)
                f.write("\n")
            f.write("\n")
            f.write(f">>> Generated by: {self.provider_model_used}")
            f.write("\n")
            f.write(">>> Final summary:\n")
            f.write("\n")
            f.write(self.final_summary)
            f.write("\n")

    def process_task(self):
        """
        Orchestrate the entire workflow to get the final summary
        """
        start_time = self.log_procesing_time(
            "Main process" +
            f"{self.args.agents_count} agent steps...")

        # Step # 1: Get high level plan from CEO
        initial_plan = self.CEO_Agent(f'{self.prompt}\n{self.user_input}')

        # Step # 2: Create agents, execute all agent steps, and get detailed
        # implementation for each step
        agents = [self.create_agent(i)
                  for i in range(1, self.args.agents_count + 1)]
        implementations = [agent(initial_plan) for agent in agents]

        # Step # 3: Combine everything to get the final summary from CEO
        self.final_input = \
            f"Initial Plan:\n{initial_plan}" + \
            "\n\nImplementations: \n" + \
            "\n".join(implementations)

        # Step # 4: Final summary
        # self.final_summary = self.CEO_Agent(self.final_input, is_final=True)
        response = self.CEO_Agent(self.final_input, is_final=True)
        self.final_summary = response

        # Save everything to a file
        self.save_result()

        self.log_procesing_time(message="Main process", start_time=start_time)
        # return self.final_summary
        return response

    def simple_processing(self):
        """
        Simple processing without agents
        """
        # messages = [
        #     {
        #         'role': 'system',
        #         'content': self.prompt
        #     },
        #     {
        #         'role': 'user',
        #         'content': self.user_input
        #     }
        # ]

        self.log_debug("")
        self.log_debug("Simple Processing messages:")
        # self.log_debug_structured(messages)

        start_time = self.log_procesing_time('Simple Processing...')

        response = self.get_model_response(
            model=self.get_model(),
            prompt=self.prompt,
            user_input=self.user_input,
            # messages=messages
        )

        self.log_procesing_time(start_time=start_time)
        self.log_debug("")
        self.log_debug('Simple Processing response:')
        self.log_debug(response)

        self.final_summary = response
        self.save_result()
        return self.final_summary

        # self.final_summary = response["response"]
        # self.save_result()
        # return response

    def generate_json(self):
        """
        Main entry point to generate the .json files
        """
        response = get_default_resultset()
        if not self.args.user_input_text and not self.args.user_input_file:
            response["error"] = True
            response["error_message"] = "User input text or file is required"
            return response

        if self.args.agents_count == 0:
            # If the number of agents is 0, we don't need to use the agents
            response["response"] = self.simple_processing()
        else:
            # Reasoning with agents
            response["response"] = self.process_task()
        return response


if __name__ == "__main__":

    json_generator = JsonGenerator()
    final_result = json_generator.generate_json()

    print("")
    print("Final result:")
    print(final_result)
    print("")
