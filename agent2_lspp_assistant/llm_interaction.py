# llm_interaction.py

import json
import requests
from collections import Counter
import sys
import time
# Import the together library for the Together AI client
try:
    from together import Together
except ImportError:
    Together = None

# Import color codes and LLM configurations from utils.py
from utils import (
    RESET, BOLD, RED, YELLOW, BLUE, MAGENTA, CYAN, WHITE, HARDCODED_COLOR,
    LLM_CONFIGS
)

# ==============================================================================
# 2. LLM Interaction Layer
#    - Defines the base class and specific implementations for LLM clients,
#      as well as the LLM factory class and configurations.
#    - Encapsulates the logic for communicating with the LLM API.
# ==============================================================================


class LLMClient:
    """Base class for LLM clients, defining a unified interface"""
    def __init__(self, config, is_selector=False): # Added is_selector parameter
        self.config = config
        self.is_selector = is_selector # Flag to indicate if this is a client used for selection
        # The headers for the Together client are handled internally by the together library, so they are not needed here
        if not isinstance(self, TogetherClient):
            self.headers = self._create_headers()

    def _create_headers(self):
        """Creates request headers, can be overridden by subclasses"""
        return {
            "Authorization": f"Bearer {self.config.get('api_token')}",
            "Content-Type": "application/json"
        }

    def generate_response(self, conversation_history, temperature=0.2, max_tokens=1500, top_p=1.0, tools=None): # Added tools parameter
        """Generates a response, must be implemented by subclasses"""
        raise NotImplementedError("Subclasses must implement the generate_response method")

class SiliconFlowClient(LLMClient):
    """SiliconFlow LLM client - Corrected Version"""
    def generate_response(self, conversation_history, temperature=0.7, max_tokens=1500, top_p=1.0, tools=None):
        # 1. 设置默认 URL：如果 config 没传 api_url，就用硅基流动官方地址
        api_url = self.config.get("api_url", "https://api.siliconflow.cn/v1/chat/completions")
        
        # 2. 构造 Payload
        payload = {
            "model": self.config.get("model"), # 模型名直接从配置读取，不要硬编码
            "messages": conversation_history,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "stream": False # 显式关闭流式传输
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            # 发送请求
            response = requests.post(api_url, json=payload, headers=self.headers, timeout=60)
            
            if response.status_code != 200:
                print(f"{RED}SiliconFlow call failed: {response.status_code}, response: {response.text}{RESET}")
                return {}, 0, 0

            llm_response = response.json()
            
            # 提取 token 使用情况
            input_tokens = llm_response.get('usage', {}).get('prompt_tokens', 0)
            output_tokens = llm_response.get('usage', {}).get('completion_tokens', 0)
            
            # --- 打印日志 (使用 CYAN 颜色) ---
            print(f"{CYAN}--- SiliconFlow API Call ---{RESET}")
            print(f"{CYAN}Model: {self.config.get('model')}{RESET}")
            print(f"{CYAN}Input Tokens: {input_tokens}{RESET}")
            print(f"{CYAN}Output Tokens: {output_tokens}{RESET}")
            print(f"{CYAN}Total Tokens: {input_tokens + output_tokens}{RESET}")
            # ----------------------------------
            
            return llm_response, input_tokens, output_tokens
        except Exception as e:
            print(f"{RED}Error calling SiliconFlow: {e}{RESET}")
            return {}, 0, 0



class OpenAIClient(LLMClient):
    """OpenAI LLM client"""
    def _create_headers(self):
        return {
            "Authorization": f"Bearer {self.config.get('api_token')}",
            "Content-Type": "application/json"
        }

    def generate_response(self, conversation_history, temperature=0.2, max_tokens=1500, top_p=1.0, tools=None):
        payload = {
            "model": self.config.get("model", "gpt-3.5-turbo"),
            "messages": conversation_history,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            response = requests.post(self.config.get("api_url", "https://api.openai.com/v1/chat/completions"),
                                    json=payload, headers=self.headers, timeout=60)
            if response.status_code != 200:
                print(f"{RED}LLM call failed: {response.status_code}, response: {response.text}{RESET}")
                return {}, 0, 0

            llm_response = response.json()
            # Extract the number of tokens
            input_tokens = llm_response.get('usage', {}).get('prompt_tokens', 0)
            output_tokens = llm_response.get('usage', {}).get('completion_tokens', 0)

            # --- Added statements to print token counts ---
            print(f"{MAGENTA}--- OpenAI API Call ---{RESET}")
            print(f"{MAGENTA}Model: {self.config.get('model')}{RESET}")
            print(f"{MAGENTA}Input Tokens: {input_tokens}{RESET}")
            print(f"{MAGENTA}Output Tokens: {output_tokens}{RESET}")
            print(f"{MAGENTA}Total Tokens: {input_tokens + output_tokens}{RESET}")
            # ----------------------------------
            
            return llm_response, input_tokens, output_tokens
        except Exception as e:
            print(f"{RED}Error calling OpenAI: {e}{RESET}")
            return {}, 0, 0


# New: Together API client
class TogetherClient(LLMClient):
    """Together API LLM client"""
    def __init__(self, config, is_selector=False):
        if Together is None:
            raise ImportError("The Together library is not installed. Please run 'pip install together' to install it.")
        self.config = config
        self.is_selector = is_selector
        self.client = Together(api_key=self.config.get('api_token'))

    def _create_headers(self):
        return {} # The Together client does not require traditional headers

    def generate_response(self, conversation_history, temperature=0.2, max_tokens=1500, top_p=1.0, tools=None):
        try:
            response_obj = self.client.chat.completions.create( # Response object
                model=self.config.get("model"),
                messages=conversation_history,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                tools=tools if tools else [],
            )

            # Extract the number of tokens
            input_tokens = response_obj.usage.prompt_tokens if response_obj.usage else 0
            output_tokens = response_obj.usage.completion_tokens if response_obj.usage else 0

            # Convert the Together response to a format similar to SF/OpenAI for unified processing of tool_calls later
            llm_response_dict = {}
            if response_obj.choices[0].message.tool_calls:
                llm_response_dict = {
                    "choices": [{
                        "message": {
                            "tool_calls": [
                                {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                for tc in response_obj.choices[0].message.tool_calls
                            ]
                        }
                    }]
                }
            else:
                llm_response_dict = {
                    "choices": [{
                        "message": {
                            "content": response_obj.choices[0].message.content
                        }
                    }]
                }
            
            # The usage field in OpenAI/SiliconFlow responses is usually at the top level. For consistency, we can add it here.
            llm_response_dict['usage'] = {
                'prompt_tokens': input_tokens,
                'completion_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens
            }

            # --- Added statements to print token counts ---
            print(f"{BLUE}--- Together API Call ---{RESET}")
            print(f"{BLUE}Model: {self.config.get('model')}{RESET}")
            print(f"{BLUE}Input Tokens: {input_tokens}{RESET}")
            print(f"{BLUE}Output Tokens: {output_tokens}{RESET}")
            print(f"{BLUE}Total Tokens: {input_tokens + output_tokens}{RESET}")
            # ----------------------------------
            
            return llm_response_dict, input_tokens, output_tokens
        except Exception as e:
            print(f"{RED}Error calling Together API: {e}{RESET}")
            return {}, 0, 0

class LLMClientFactory:
    """LLM client factory class, used to create different types of LLM clients"""
    
    # === 1. 硅基流动 (SiliconFlow) 支持的模型列表 ===
    siliconflow_models = [
        # DeepSeek 系列
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-V3.2",
        "deepseek-ai/DeepSeek-R1",
        "deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "Pro/deepseek-ai/DeepSeek-V3", 
        "Pro/deepseek-ai/DeepSeek-R1",
        
        # Qwen (通义千问) 系列
        "Qwen/Qwen2.5-72B-Instruct",
        "Qwen/Qwen2.5-Coder-32B-Instruct",
        "Qwen/Qwen2.5-7B-Instruct",
        
        # GLM (智谱) 系列
        "THUDM/glm-4-9b-chat",
    ]

    openai_models = [
        "gpt-3.5-turbo",
        "gpt-4o",
    ]

    # === 2. Together AI 支持的模型列表 ===
    together_models = [
        # Llama 3 系列
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
        "meta-llama/Meta-Llama-3-8B-Instruct-Lite", # 最新版 Llama
        
        # Qwen 系列 (Together 版)
        # 注意：如果同一模型名在两个列表都存在，根据下面 create_client 的判断顺序决定优先用谁
        # "Qwen/Qwen2.5-Coder-32B-Instruct", 
        
        # Mistral / Mixtral
        "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "mistralai/Mixtral-8x22B-Instruct-v0.1",
        
        # Google Gemma
        "google/gemma-2-27b-it",
    ]

    @staticmethod
    def create_client(llm_model_name, config, is_selector=False): 
        # 逻辑：根据模型名称所在的列表，实例化对应的 Client
        
        if llm_model_name in LLMClientFactory.siliconflow_models:
            return SiliconFlowClient(config, is_selector=is_selector)
            
        elif llm_model_name in LLMClientFactory.together_models:
            return TogetherClient(config, is_selector=is_selector)
            
        elif llm_model_name in LLMClientFactory.openai_models:
            return OpenAIClient(config, is_selector=is_selector)
            
        else:
            # 增加更友好的错误提示，方便你排查是不是模型名字写错了
            error_msg = (
                f"{RED}Unsupported LLM model name: '{llm_model_name}'. "
                f"Please add it to the corresponding list (siliconflow_models or together_models) in LLMClientFactory.{RESET}"
            )
            raise ValueError(error_msg)

# Global DeepSeek-V3 client instance for result selection
global_deepseek_v3_selector_client = None
DEEPSEEK_V3_MODEL_NAME_CLEAN = "Pro/deepseek-ai/DeepSeek-V3" # Define a constant for easy comparison

def get_deepseek_v3_selector_client():
    """Lazy initializes the DeepSeek-V3 client"""
    global global_deepseek_v3_selector_client
    if global_deepseek_v3_selector_client is None:
        deepseek_config = LLM_CONFIGS.get(DEEPSEEK_V3_MODEL_NAME_CLEAN)
        if not deepseek_config:
            print(f"{RED}Error: Configuration for DeepSeek-V3 'LLM_CONFIGS[\"{DEEPSEEK_V3_MODEL_NAME_CLEAN}\"]' does not exist.{RESET}")
            raise ValueError(f"DeepSeek-V3 configuration is missing.")

        # Clear color tags so that the client can parse the model name correctly
        deepseek_config_clean = {
            k: v.replace(HARDCODED_COLOR, '').replace(RESET, '') if isinstance(v, str) else v
            for k, v in deepseek_config.items()
        }
        try:
            # The DeepSeek-V3 auxiliary selector itself is marked as is_selector=True
            global_deepseek_v3_selector_client = LLMClientFactory.create_client(
                DEEPSEEK_V3_MODEL_NAME_CLEAN, deepseek_config_clean, is_selector=True
            )
            print(f"{BLUE}Successfully initialized DeepSeek-V3 result selection client.{RESET}")
        except Exception as e:
            print(f"{RED}Failed to initialize DeepSeek-V3 result selection client: {e}{RESET}")
            raise
    return global_deepseek_v3_selector_client


def canonicalize_llm_response(response_json):
    """
    Standardizes the LLM response into a comparable string format for counting.
    Specifically handles tool calls and normal content responses.
    """
    if not response_json or not response_json.get('choices'):
        return None

    message = response_json['choices'][0]['message']

    if message.get('tool_calls'):
        # Extract the name and arguments of the tool call, and stringify the arguments JSON with sorted keys to ensure consistency
        tool_calls_data = []
        for tc in message['tool_calls']:
            function_name = tc['function']['name']
            # For arguments, first parse them into a dictionary and then use json.dumps with sorted keys to ensure consistent order
            try:
                args = json.loads(tc['function']['arguments'])
                canonical_args = json.dumps(args, sort_keys=True, separators=(',', ':'))
            except json.JSONDecodeError:
                canonical_args = tc['function']['arguments'] # If it is not a valid JSON, use the original string directly
            tool_calls_data.append(f"{function_name}({canonical_args})")
        return f"TOOL_CALLS: {sorted(tool_calls_data)}" # Sort multiple tool calls
    elif message.get('content'):
        return f"CONTENT: {message['content']}"
    return None # Unparsable response


# --- Large Model Call Function ---
def call_llm(llm_client_instance, messages, tools, num_calls=10, call_delay=0.5, is_initial_user_query=False):
    """
    Calls the LLM.
    - If it is the user's first query (is_initial_user_query=True) and the current client is not the DeepSeek-V3 selector,
      it performs num_calls model calls and uses majority voting, and may call DeepSeek-V3 for secondary confirmation.
    - If it is a subsequent internal thought process or tool result feedback (is_initial_user_query=False),
      or if the current client is the DeepSeek-V3 selector, it performs only a single model call.

    Returns: (llm_response_dict, total_input_tokens, total_output_tokens)
    """
    config = llm_client_instance.config
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens", 512)
    top_p = config.get("top_p", 0.7)

    # Initialize the total token count, this is for the sum of all calls returned by the function (including DeepSeek-V3)
    total_input_tokens_overall = 0
    total_output_tokens_overall = 0

    # 1. Determine whether to make a single call
    if not is_initial_user_query or llm_client_instance.is_selector:
        try:
            print(f"{YELLOW}LLM-Helper: Not the first user request or DeepSeek-V3 selector, performing a single model call...{RESET}")
            # generate_response returns (llm_response_dict, input_tokens, output_tokens)
            llm_response_dict, input_tokens, output_tokens = llm_client_instance.generate_response(
                conversation_history=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                tools=tools
            )
            total_input_tokens_overall += input_tokens if input_tokens is not None else 0
            total_output_tokens_overall += output_tokens if output_tokens is not None else 0

            return llm_response_dict, total_input_tokens_overall, total_output_tokens_overall
        except requests.exceptions.RequestException as e:
            print(f"{RED}A network error occurred during the LLM call: {e}{RESET}")
            return {}, 0, 0 # Return an empty dictionary and 0 tokens on failure
        except Exception as e:
            print(f"{RED}An unknown error occurred during the LLM call: {e}{RESET}")
            return {}, 0, 0 # Return an empty dictionary and 0 tokens on failure

    # 2. For the user's first query, and not the DeepSeek-V3 selector, execute multiple LLM calls and probability selection logic
    all_responses_with_tokens = [] # Stores (llm_response_dict, input_tokens, output_tokens)

    # Initialize token count for the 10-call loop
    input_tokens_10_calls = 0
    output_tokens_10_calls = 0

    print(f"{YELLOW}LLM-Helper: First user request, performing {num_calls} model calls to enhance stability...{RESET}")
    for i in range(num_calls):
        try:
            # generate_response returns (llm_response_dict, input_tokens, output_tokens)
            llm_response_dict, input_tokens, output_tokens = llm_client_instance.generate_response(
                conversation_history=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                tools=tools
            )
            if llm_response_dict: # Add and accumulate only when the response dictionary is not empty
                all_responses_with_tokens.append((llm_response_dict, input_tokens, output_tokens))
                input_tokens_10_calls += input_tokens if input_tokens is not None else 0
                output_tokens_10_calls += output_tokens if output_tokens is not None else 0
        except Exception as e:
            print(f"{YELLOW}Warning: The {i+1}th LLM call failed: {e}{RESET}")
        
        if i < num_calls - 1:
            time.sleep(call_delay) 

    # --- Output total tokens after 10 calls ---
    print(f"{CYAN}--- LLM {num_calls} Calls Total ---{RESET}")
    print(f"{CYAN}Total Input Tokens: {input_tokens_10_calls}{RESET}")
    print(f"{CYAN}Total Output Tokens: {output_tokens_10_calls}{RESET}")
    print(f"{CYAN}Total Tokens: {input_tokens_10_calls + output_tokens_10_calls}{RESET}")
    # ------------------------------------

    # Also add the tokens from these 10 calls to the overall total
    total_input_tokens_overall += input_tokens_10_calls
    total_output_tokens_overall += output_tokens_10_calls


    if not all_responses_with_tokens:
        print(f"{RED}LLM-Helper: All {num_calls} LLM calls failed.{RESET}")
        return {}, 0, 0 # Return an empty dictionary and 0 tokens on failure

    # Standardize and count results
    canonical_results = [] # Stores (canonical_form, llm_response_dict)
    for llm_resp_dict, _, _ in all_responses_with_tokens: # Unpack, only take llm_response_dict
        canonical = canonicalize_llm_response(llm_resp_dict) # Pass in the LLM response dictionary
        if canonical:
            canonical_results.append((canonical, llm_resp_dict)) # Store the standardized result and the original response dictionary
    
    if not canonical_results:
        print(f"{RED}LLM-Helper: Could not parse any valid results from {num_calls} calls.{RESET}")
        return {}, 0, 0 # Return an empty dictionary and 0 tokens on failure

    # Count the frequency of occurrence
    counts = Counter(cr[0] for cr in canonical_results)
    most_common_canonical_form = counts.most_common(1)[0][0]
    
    # Find the first original response dictionary that matches the most common standardized form
    final_chosen_response_dict = None
    for canonical_form, original_llm_response_dict in canonical_results:
        if canonical_form == most_common_canonical_form:
            final_chosen_response_dict = original_llm_response_dict
            break # Exit after finding the first match

    if not final_chosen_response_dict:
        print(f"{RED}LLM-Helper: Failed to find an original response that matches the highest probability result.{RESET}")
        return {}, 0, 0 # Return an empty dictionary and 0 tokens on failure

    # 3. If the current LLM is not DeepSeek-V3, call DeepSeek-V3 for auxiliary confirmation (single call)
    current_llm_model_name_clean = llm_client_instance.config.get("model").replace(HARDCODED_COLOR, '').replace(RESET, '')
    if current_llm_model_name_clean != DEEPSEEK_V3_MODEL_NAME_CLEAN:
        try:
            deepseek_selector = get_deepseek_v3_selector_client()
            
            selection_prompt_messages = [
                {"role": "system", "content": "You are an intelligent decision-making assistant. You will be given a list containing the output results of an LLM after multiple calls and their frequencies. Your task is to accurately identify and return the original result with the highest frequency. Please only return the selected original JSON object (if it contains tool_calls) or the original text content (if it contains content), without adding any extra text."},
                {"role": "user", "content": "This is the statistical information of multiple LLM call results, where each result includes its original form and the number of occurrences after standardization.\n\nPlease select and return the original result with the highest frequency. If there are multiple results with the same highest frequency, please choose any one of them to return.\n\nResult list:\n"}
            ]

            result_details = []
            for canonical_form, count in counts.most_common():
                original_resp_for_canonical = next((resp_dict for cf, resp_dict in canonical_results if cf == canonical_form), None)
                if original_resp_for_canonical:
                    result_details.append({
                        "count": count,
                        "canonical_form": canonical_form,
                        "original_response": original_resp_for_canonical # Contains the original JSON dictionary
                    })
            
            selection_prompt_messages[-1]["content"] += json.dumps(result_details, indent=2, ensure_ascii=False) + "\n\nPlease strictly return only the `original_response` part of your selected response."

            print(f"{YELLOW}LLM-Helper: Using DeepSeek-V3 to confirm the highest probability result (single call)...{RESET}")
            # generate_response returns (llm_response_dict, input_tokens, output_tokens)
            deepseek_selection_response_dict, deepseek_input_tokens, deepseek_output_tokens = deepseek_selector.generate_response(
                conversation_history=selection_prompt_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                tools=None
            )

            # Regardless of whether DeepSeek-V3 successfully makes a selection, its own tokens will be included in the overall total
            total_input_tokens_overall += deepseek_input_tokens if deepseek_input_tokens is not None else 0
            total_output_tokens_overall += deepseek_output_tokens if deepseek_output_tokens is not None else 0

            if deepseek_selection_response_dict and deepseek_selection_response_dict.get('choices') and deepseek_selection_response_dict['choices'][0]['message'].get('content'):
                try:
                    chosen_by_deepseek = json.loads(deepseek_selection_response_dict['choices'][0]['message']['content'])
                    final_chosen_response_dict = chosen_by_deepseek
                    print(f"{BLUE}LLM-Helper: DeepSeek-V3 successfully selected a result.{RESET}")
                except json.JSONDecodeError:
                    print(f"{YELLOW}Warning: The response from DeepSeek-V3 is not valid JSON, will use internal statistics.{RESET}")
            else:
                print(f"{YELLOW}Warning: DeepSeek-V3 failed to select a result, will use internal statistics.{RESET}")
        except Exception as e:
            print(f"{RED}Error: An exception occurred when calling DeepSeek-V3 to select a result: {e}. Will use internal statistics.{RESET}")
    
    print(f"{BLUE}LLM-Helper: Multiple calls completed, selected the result that appeared {counts[most_common_canonical_form]} times ({most_common_canonical_form[:50]}...).{RESET}")
    # The return value is the sum including the DeepSeek-V3 call
    return final_chosen_response_dict, total_input_tokens_overall, total_output_tokens_overall
