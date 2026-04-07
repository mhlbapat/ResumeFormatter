from langchain_openai import ChatOpenAI
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from modules.agent.tools import create_tools

def build_agent(app_state):
    # Initialize the LLM the agent will use for reasoning (the "brain")
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    # Load all the tools we wrapped
    tools = create_tools(app_state)
    
    # Create the agent prompt
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an autonomous Job Application Agent. You help users generate tailored resumes and autofill job applications. Use the provided tools to accomplish these tasks. If a user asks to generate a resume, make sure you collect the job title, company, location, and a sufficiently detailed description before calling the tool. Be concise."),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    # Construct the tools-based agent
    agent = create_tool_calling_agent(llm, tools, prompt)
    
    # Wrap it in an AgentExecutor which handles the tool-calling loop and error handling
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
    return agent_executor
