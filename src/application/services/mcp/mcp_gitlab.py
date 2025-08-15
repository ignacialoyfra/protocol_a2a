import os, asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_aws.chat_models import ChatBedrock
from langgraph.prebuilt import create_react_agent


async def main():
    client = MultiServerMCPClient({

        "gitlab_extra_py": {
            "command": "python",
            "args": ["gitlab_sidecar.py"],
            "transport": "stdio",
            "env": {
                "GITLAB_API_URL": "https://gitlab.com/api/v4",
                "GITLAB_PERSONAL_ACCESS_TOKEN": os.environ["GITLAB_PERSONAL_ACCESS_TOKEN"],
            },
        },
        "gitlab_mcp": {
            "command": "docker",
            "args": [
                "run", "--rm", "-i",
                "-e", f"GITLAB_API_URL=https://gitlab.com/api/v4",
                "-e", f"GITLAB_PERSONAL_ACCESS_TOKEN={os.environ['GITLAB_PERSONAL_ACCESS_TOKEN']}",
                "mcp/gitlab"
            ],
            "transport": "stdio"
        }
    })

    tools = await client.get_tools()
    print(f"Herramientas disponibles: {tools}")

    model = ChatBedrock(model="anthropic.claude-3-haiku-20240307-v1:0",region="us-east-1")  
    agent = create_react_agent(model, tools,prompt=(
        "Eres un agente de GitLab. "
        "Usa EXCLUSIVAMENTE las herramientas MCP disponibles. "
        "Nunca pidas credenciales al usuario. "
        "Si no existe una tool para algo, dilo explícitamente."
    ))
    response = await agent.ainvoke({
        "messages": [{"role": "user", "content": "Cuantos proyectos tengo aqui https://gitlab.com/laboratorios6515333/cicd/pipeline_test ?"}]
    })
    print(response["messages"][-1].content)
    

asyncio.run(main())
