from openai import OpenAI
import os 

client = OpenAI(
  base_url = "https://integrate.api.nvidia.com/v1",
  api_key = os.environ["NVIDIA_API_KEY"]
)

system_prompt = """ 
You are an expert of playing puzzle games , you are currently playing a text-based game called ALFWorld.
You will be given a description of the game , the goal of the game, and a list of actions you can take.

"""
completion = client.chat.completions.create(
  model="nvidia/llama-3.3-nemotron-super-49b-v1.5",
  messages=[{"role":"system","content":"/think"}],
  temperature=0.6,
  top_p=0.95,
  max_tokens=65536,
  frequency_penalty=0,
  presence_penalty=0,
  stream=True
)

for chunk in completion:
  if chunk.choices[0].delta.content is not None:
    print(chunk.choices[0].delta.content, end="")

