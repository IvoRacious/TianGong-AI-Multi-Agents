import json
import os
from datetime import timedelta
from functools import partial

import httpx
from airflow import DAG
from airflow.models import Variable
from airflow.operators.empty import EmptyOperator as DummyOperator
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.sensors.time_delta import TimeDeltaSensor
from httpx import RequestError

BASE_URL = "http://host.docker.internal:8000"
TOKEN = Variable.get("FAST_API_TOKEN")

agent_url = "/openai_agent/invoke"
openai_url = "/openai/invoke"
summary_url = "/esg_governance_agent/invoke"

session_id = "20240120"


task_summary_prompt = """Based on the input, provide a summarized paragraph for each task. You must follow the structure in Markdown format like below (change the title to the task ID):

    ### Governance 6 (a) - 1 or Governance 6 (a)
    A conclusion sentence about information disclosure. Specific explanations (NO bulletin points).
    ### Governance 6 (a) - 2 or Governance 6 (b)
    A conclusion sentence about information disclosure. Specific explanations (NO bulletin points).
    ...
    (Continue with additional task IDs and their summaries)"""


def post_request(
    post_url: str,
    formatter: callable,
    ti: any,
    data_to_send: dict = None,
):
    if not data_to_send:
        data_to_send = formatter(ti)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=600) as client:
        try:
            response = client.post(post_url, json=data_to_send)

            response.raise_for_status()

            data = response.json()

            return data

        except RequestError as req_err:
            print(f"An error occurred during the request: {req_err}")
        except Exception as err:
            print(f"An unexpected error occurred: {err}")


def task_PyOpr(
    task_id: str,
    callable_func,
    # retries: int = 3,
    # retry_delay=timedelta(seconds=3),
    execution_timeout=timedelta(minutes=10),
    op_kwargs: dict = None,
):
    return PythonOperator(
        task_id=task_id,
        python_callable=callable_func,
        # retries=retries,
        # retry_delay=retry_delay,
        execution_timeout=execution_timeout,
        op_kwargs=op_kwargs,
    )


def agent_formatter(ti, prompt: str = "", task_ids: list = None, session_id: str = ""):
    if task_ids:
        results = []
        for task_id in task_ids:
            data = ti.xcom_pull(task_ids=task_id)
            task_output = data["output"]["output"]  # Output from agent
            task_output_with_id = (
                f"{task_id}:\n {task_output}"  # Concatenate task ID with its output
            )
            results.append(task_output_with_id)
        content = "\n\n".join(results)  # Join all task results into a single string
        formatted_data = {
            "input": {"input": prompt + "\n\n INPUT:" + content},
            "config": {"configurable": {"session_id": session_id}},
        }
        return formatted_data
    else:
        pass


def openai_formatter(ti, prompt: str = None, task_ids: list = None):
    results = []
    for task_id in task_ids:
        data = ti.xcom_pull(task_ids=task_id)
        task_output = data["output"]["output"]  # Output from agent
        task_output_with_id = (
            f"{task_id}:\n {task_output}"  # Concatenate task ID with its output
        )
        results.append(task_output_with_id)
    content = "\n\n".join(results)  # Join all task results into a single string
    if prompt:
        content = prompt + "\n\n" + content
    formatted_data = {"input": content}
    return formatted_data


def determine_branch(ti):
    data = ti.xcom_pull(task_ids="determine_path")["output"]["content"]
    data = data.strip().lower()
    if data == "no":
        return "Strategy_21_a", "Strategy_21_b", "Strategy_21_c"
    else:
        return []


def openai_translate_formatter(ti, task_id=["merge"]):
    data = ti.xcom_pull(task_ids=task_id)
    content = "Translate the following text into native Chinese:" + "\n\n" + str(data)
    formatted_data = {"input": content}
    return formatted_data


def merge(ti):
    result_0 = ti.xcom_pull(task_ids="Governance_overview")["output"]["output"]
    result_1 = ti.xcom_pull(task_ids="Governance_6_a_overview")["output"]["output"]
    result_2 = ti.xcom_pull(task_ids="Governance_6_a_task_summary")["output"]["output"]
    result_3 = ti.xcom_pull(task_ids="Governance_6_b_overview")["output"]["output"]
    result_4 = ti.xcom_pull(task_ids="Governance_6_b_task_summary")["output"]["output"]
    result_5 = ti.xcom_pull(task_ids="Strategy_overview")["output"]["output"]
    result_6 = ti.xcom_pull(task_ids="Strategy_10_overview")["output"]["output"]
    result_7 = ti.xcom_pull(task_ids="Strategy_10_task_summary")["output"]["output"]
    result_8 = ti.xcom_pull(task_ids="Strategy_11_overview")["output"]["output"]
    result_9 = ti.xcom_pull(task_ids="Strategy_13_overview")["output"]["output"]
    result_10 = ti.xcom_pull(task_ids="Strategy_13_task_summary")["output"]["output"]

    concatenated_result = (
        " # Governance\n"
        + result_0
        + "\n\n"
        + "## Governance 6 (a)\n"
        + result_1
        + "\n\n"
        + result_2
        + "\n\n"
        + "## Governance 6 (b)\n"
        + result_3
        + "\n\n"
        + result_4
        + "\n\n"
        + "# Strategy\n"
        + result_5
        + "\n\n"
        + "## Strategy 10\n"
        + result_6
        + "\n\n"
        + result_7
        + "\n\n"
        + "## Strategy 11\n"
        + result_8
        + "\n\n"
        + "## Strategy 13\n"
        + result_9
        + "\n\n"
        + result_10
    )

    markdown_file_name = "ESG_compliance_report_EN.md"

    # Save the model's response to a Markdown file
    with open(markdown_file_name, "w") as markdown_file:
        markdown_file.write(concatenated_result)
    return concatenated_result


def save_file(ti, file_name: str = "ESG_compliance_report_CN.md"):
    data = ti.xcom_pull(task_ids="translate")["output"]["content"]
    with open(file_name, "w") as markdown_file:
        markdown_file.write(data)
    return data


gov_a_task_summary_formatter = partial(
    agent_formatter,
    prompt=task_summary_prompt,
    task_ids=[
        "Governance_6_a_1",
        "Governance_6_a_2",
        "Governance_6_a_3",
        "Governance_6_a_4",
        "Governance_6_a_5",
    ],
    session_id=session_id,
)
gov_b_task_summary_formatter = partial(
    agent_formatter,
    prompt=task_summary_prompt,
    task_ids=["Governance_6_b_1", "Governance_6_b_2"],
    session_id=session_id,
)
gov_a_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report discloses information about the governance body(s) or individual(s) responsible for oversight of climate-related risks and opportunities, into ONE paragraph.",
    task_ids=[
        "Governance_6_a_1",
        "Governance_6_a_2",
        "Governance_6_a_3",
        "Governance_6_a_4",
        "Governance_6_a_5",
    ],
    session_id=session_id,
)
gov_b_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report discloses information about management’s role in the governance processes, controls and procedures used to monitor, manage and oversee climate-related risks and opportunities, into ONE paragraph.",
    task_ids=["Governance_6_b_1", "Governance_6_b_2"],
    session_id=session_id,
)
gov_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report discloses information that enable users of general purpose financial reports to understand the governance processes, controls and procedures an entity uses to monitor, manage and oversee climate-related risks and opportunities, into ONE paragraph.",
    task_ids=[
        "Governance_6_a_overview",
        "Governance_6_b_overview",
    ],
    session_id=session_id,
)
strategy_10_task_summary_formatter = partial(
    agent_formatter,
    prompt=task_summary_prompt,
    task_ids=["Strategy_10_a", "Strategy_10_b", "Strategy_10_c", "Strategy_10_d"],
    session_id=session_id,
)
strategy_10_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report discloses information that enables users of general purpose financial reports to understand the climate-related risks and opportunities that could reasonably be expected to affect the entity’s prospects, into ONE paragraph.",
    task_ids=["Strategy_10_a", "Strategy_10_b", "Strategy_10_c", "Strategy_10_d"],
    session_id=session_id,
)
strategy_11_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report use all reasonable and supportable information that is available to the entity at the reporting date without undue cost or effort, including information about past events, current conditions and forecasts of future conditions, into ONE paragraph.",
    task_ids=["Strategy_11"],
    session_id=session_id,
)
strategy_13_task_summary_formatter = partial(
    agent_formatter,
    prompt=task_summary_prompt,
    task_ids=["Strategy_13_a", "Strategy_13_b"],
    session_id=session_id,
)
strategy_13_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report discloses information that enables users of general purpose financial reports to understand the current and anticipated effects of climate - related risks and opportunities on the entity’s business model and value chain, into ONE paragraph.",
    task_ids=["Strategy_13_a", "Strategy_13_b"],
    session_id=session_id,
)
strategy_14_a_summary_formatter = partial(
    agent_formatter,
    prompt=task_summary_prompt,
    task_ids=[
        "Strategy_14_a_1",
        "Strategy_14_a_2",
        "Strategy_14_a_3",
        "Strategy_14_a_4",
    ],
    session_id=session_id,
)
strategy_14_a_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report discloses information about how the entity has responded to, and plans to respond to, climate-related risks and opportunities in its strategy and decision-making, including how the entity plans to achieve any climate-related targets it has set and any targets it is required to meet by law or regulation, into ONE paragraph.",
    task_ids=[
        "Strategy_14_a_1",
        "Strategy_14_a_2",
        "Strategy_14_a_3",
        "Strategy_14_a_4",
    ],
    session_id=session_id,
)
strategy_14_b_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report discloses information about how the entity is resourcing, and plans to resource, the activities disclosed in accordance with following input, into ONE paragraph.",
    task_ids=["Strategy_14_a_overview"],
    session_id=session_id,
)
strategy_14_c_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report discloses quantitative and qualitative information about the progress of plans disclosed in previous reporting  periods  in  accordance  with following input, into ONE paragraph.",
    task_ids=["Strategy_14_a_overview"],
    session_id=session_id,
)
strategy_14_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report discloses information that enables users of general purpose financial reports to understand the effects of climate-related risks and opportunities on its strategy and decision-making, into ONE paragraph.",
    task_ids=[
        "Strategy_14_a_overview",
        "Strategy_14_b",
        "Strategy_14_c",
    ],
    session_id=session_id,
)
strategy_15_task_summary_formatter = partial(
    agent_formatter,
    prompt=task_summary_prompt,
    task_ids=["Strategy_15_a", "Strategy_15_b"],
    session_id=session_id,
)
strategy_15_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE into ONE paragraph.",
    task_ids=["Strategy_15_a", "Strategy_15_b"],
    session_id=session_id,
)
strategy_16_b_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE whether the report discloses quantitative and qualitative information about the  climate-related  risks  and   opportunities   identified   in the following input, for which there is a significant risk of a material adjustment within the next annual reporting period to the carrying amounts of assets and liabilities reported in the related financial statements, into ONE paragraph",
    task_ids=["Strategy_16_a"],
    session_id=session_id,
)
strategy_16_task_summary_formatter = partial(
    agent_formatter,
    prompt=task_summary_prompt,
    task_ids=[
        "Strategy_16_a",
        "Strategy_16_b",
        "Strategy_16_c_1",
        "Strategy_16_c_2",
        "Strategy_16_d",
    ],
    session_id=session_id,
)
strategy_16_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE into ONE paragraph.",
    task_ids=[
        "Strategy_16_a",
        "Strategy_16_b",
        "Strategy_16_c_1",
        "Strategy_16_c_2",
        "Strategy_16_d",
    ],
    session_id=session_id,
)
strategy_17_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE into ONE paragraph.",
    task_ids=[
        "Strategy_14_c",
        "Strategy_16_task_summary",
    ],
    session_id=session_id,
)
strategy_18_task_summary_formatter = partial(
    agent_formatter,
    prompt=task_summary_prompt,
    task_ids=["Strategy_18_a", "Strategy_18_b"],
    session_id=session_id,
)
strategy_18_overview_formatter = partial(
    agent_formatter,
    prompt="Based on the input, SUMMARIZE into ONE paragraph.",
    task_ids=["Strategy_18_a", "Strategy_18_b"],
    session_id=session_id,
)
strategy_19_task_summary_formatter = partial(
    agent_formatter,
    prompt=task_summary_prompt,
    task_ids=["Strategy_19_a", "Strategy_19_b"],
    session_id=session_id,
)
strategy_19_overview_formatter = partial(
    agent_formatter,
    prompt="""Based on the following criteria and input, SUMMARIZE whether an entity need provide quantitative information about the current or anticipated financial effects of a climate-related risk or opportunity, into ONE paragraph?.

    Criteria:
    An entity need not provide quantitative information if the entity determines that those effects are not separately identifiable; or the level of measurement uncertainty involved in estimating those effects is so high that the resulting quantitative information would not be useful.""",
    task_ids=["Strategy_19_a", "Strategy_19_b"],
    session_id=session_id,
)
strategy_20_task_summary_formatter = partial(
    agent_formatter,
    prompt="""Based on the following criteria and input, SUMMARIZE whether an entity need provide quantitative information about anticipated financial effects of a climate-related risk or opportunity, into ONE paragraph. 
    
    Criteria:
    An entity need not provide quantitative information about the anticipated financial effects of a climate-related risk or opportunity if the entity does not have the skills, capabilities or resources to provide that quantitative information.""",
    task_ids=["Strategy_20"],
    session_id=session_id,
)
determine_path_formatter = partial(
    openai_formatter,
    prompt="Based on the input, DETERMINE whether entity need provide quantitative information about the current or anticipated financial effects of a climate-related risk or opportunity. MUST respond with YES or NO ONLY.",
    task_ids=["Strategy_19_overview", "Strategy_20_task_summary"],
)


governance_openai_formatter = partial(
    openai_formatter,
    prompt="""Based on the following upstream outputs, provide a summary for each task related to the disclosure of how governance bodies or individuals are responsible for the oversight of climate-related risks and opportunities. You must follow the structure below:
    # Governance
    ## Governance 6 (a) - 1
    A concise summary of the disclosure in the task.
    ## Governance 6 (a) - 2
    A concise summary of the disclosure in the task.
    ...
    (Continue with additional task IDs and their summaries)

    Upstream outputs:
    """,
    task_ids=["Governance_6_a_1", "Governance_6_a_2"],
)


agent = partial(post_request, post_url=agent_url, formatter=agent_formatter)
# openai = partial(post_request, post_url=openai_url, formatter=openai_formatter)
openai_governance = partial(
    post_request, post_url=openai_url, formatter=governance_openai_formatter
)
govenance_a_task_summary_agent = partial(
    post_request, post_url=summary_url, formatter=gov_a_task_summary_formatter
)
govenance_b_task_summary_agent = partial(
    post_request, post_url=summary_url, formatter=gov_b_task_summary_formatter
)
govenance_a_overview_agent = partial(
    post_request, post_url=summary_url, formatter=gov_a_overview_formatter
)
govenance_b_overview_agent = partial(
    post_request, post_url=summary_url, formatter=gov_b_overview_formatter
)
govenance_overview_agent = partial(
    post_request, post_url=summary_url, formatter=gov_overview_formatter
)
strategy_10_task_summary_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_10_task_summary_formatter
)
strategy_10_overview_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_10_overview_formatter
)
strategy_11_overview_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_11_overview_formatter
)
strategy_13_task_summary_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_13_task_summary_formatter
)
strategy_13_overview_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_13_overview_formatter
)
strategy_14_a_task_summary_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_14_a_summary_formatter
)
strategy_14_a_overview_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_14_a_overview_formatter
)
strategy_14_b_agent = partial(
    post_request, post_url=agent_url, formatter=strategy_14_b_formatter
)
strategy_14_c_agent = partial(
    post_request, post_url=agent_url, formatter=strategy_14_c_formatter
)
strategy_14_overview_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_14_overview_formatter
)
strategy_15_task_summary_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_15_task_summary_formatter
)
strategy_15_overview_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_15_overview_formatter
)
strategy_16_b_agent = partial(
    post_request, post_url=agent_url, formatter=strategy_16_b_formatter
)
strategy_16_task_summary_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_16_task_summary_formatter
)
strategy_16_overview_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_16_overview_formatter
)
strategy_18_task_summary_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_18_task_summary_formatter
)
strategy_18_overview_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_18_overview_formatter
)
strategy_19_task_summary_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_19_task_summary_formatter
)
strategy_19_overview_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_19_overview_formatter
)
strategy_20_task_summary_agent = partial(
    post_request, post_url=summary_url, formatter=strategy_20_task_summary_formatter
)
determine_path_agent = partial(
    post_request, post_url=openai_url, formatter=determine_path_formatter
)

translate_agent = partial(
    post_request, post_url=openai_url, formatter=openai_translate_formatter
)

default_args = {
    "owner": "airflow",
}


with DAG(
    dag_id="ESG_new",
    default_args=default_args,
    description="ESG compliance Agent DAG",
    schedule_interval=None,
    tags=["ESG_agent"],
    catchup=False,
) as dag:
    Governance_6_a_1 = task_PyOpr(
        task_id="Governance_6_a_1",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose information about: how responsibilities for climate-related risks and opportunities are reflected in the terms of reference, mandates, role descriptions and other related policies applicable to that body(s) or individual(s)?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Governance_6_a_2 = task_PyOpr(
        task_id="Governance_6_a_2",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Dose the report disclose information about: how the body(s) or individual(s) determines whether appropriate skills and competencies are available or will be developed to oversee strategies designed to respond to climate-related risks and opportunities?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Governance_6_a_3 = task_PyOpr(
        task_id="Governance_6_a_3",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Dose the report disclose information about: how and how often the body(s) or individual(s) is informed about climate-related risks and opportunities?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Governance_6_a_4 = task_PyOpr(
        task_id="Governance_6_a_4",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Dose the report disclose information about: how the body(s) or individual(s) takes into account climate-related risks and opportunities when overseeing the entity’s strategy, its decisions on major transactions and its risk management processes and related policies, including whether the body(s) or individual(s) has considered trade-offs associated with those risks and opportunities?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Governance_6_a_5 = task_PyOpr(
        task_id="Governance_6_a_5",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Dose the report disclose information about: how the body(s) or individual(s) oversees the setting of targets related to climate-related risks and opportunities, and monitors progress towards those targets, including whether and how related performance metrics are included in remuneration policies?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Governance_6_a_overview = task_PyOpr(
        task_id="Governance_6_a_overview",
        callable_func=govenance_a_overview_agent,
    )

    Governance_6_a_task_summary = task_PyOpr(
        task_id="Governance_6_a_task_summary",
        callable_func=govenance_a_task_summary_agent,
    )

    Governance_6_b_1 = task_PyOpr(
        task_id="Governance_6_b_1",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Dose the report disclose information about: whether the management’s role in the governance processes, controls and procedures used to monitor, manage and oversee climate-related risks and opportunities is delegated to a specific management-level position or management-level committee and how oversight is exercised over that position or committee?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Governance_6_b_2 = task_PyOpr(
        task_id="Governance_6_b_2",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Dose the report disclose information about: whether management uses controls and procedures to support the oversight of climate-related risks and opportunities and, if so, how these controls and procedures are integrated  with other internal functions?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Governance_6_b_overview = task_PyOpr(
        task_id="Governance_6_b_overview",
        callable_func=govenance_b_overview_agent,
    )

    Governance_6_b_task_summary = task_PyOpr(
        task_id="Governance_6_b_task_summary",
        callable_func=govenance_b_task_summary_agent,
    )

    Governance_overview = task_PyOpr(
        task_id="Governance_overview",
        callable_func=govenance_overview_agent,
    )

    Strategy_10_a = task_PyOpr(
        task_id="Strategy_10_a",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report describe climate-related risks and opportunities that could reasonably be expected to affect the entity’s prospects?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_10_b = task_PyOpr(
        task_id="Strategy_10_b",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report explain, for each climate-related risk the entity has identified, whether the entity considers the risk to be a climate-related physical risk or climate-related transition risk?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_10_c = task_PyOpr(
        task_id="Strategy_10_c",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report specify, for each climate-related risk and opportunity the entity has identified, over which time horizons—short, medium or long term— the effects of each climate-related risk and opportunity could reasonably be expected to occur?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_10_d = task_PyOpr(
        task_id="Strategy_10_d",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report explain how the entity defines ‘short term’, ‘medium term’ and ‘long term’ and how these definitions are linked to the planning horizons used by the entity for strategic decision-making?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_10_task_summary = task_PyOpr(
        task_id="Strategy_10_task_summary",
        callable_func=strategy_10_task_summary_agent,
    )

    Strategy_10_overview = task_PyOpr(
        task_id="Strategy_10_overview",
        callable_func=strategy_10_overview_agent,
    )

    Strategy_11 = task_PyOpr(
        task_id="Strategy_11",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "In identifying the climate-related risks and opportunities that could reasonably be expected to affect an entity’s prospects, does the report use all reasonable and supportable information that is available to the entity at the reporting date without undue cost or effort, including information about past events, current conditions and forecasts of future conditions?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_11_overview = task_PyOpr(
        task_id="Strategy_11_overview",
        callable_func=strategy_11_overview_agent,
    )

    Strategy_13_a = task_PyOpr(
        task_id="Strategy_13_a",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose a description of the current and anticipated effects of climate-related risks and opportunities on the entity’s business model and value chain?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_13_b = task_PyOpr(
        task_id="Strategy_13_b",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose a description of where in the entity’s business model and value chain climate-related risks and opportunities are concentrated (for example, geographical areas, facilities and types of assets)?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_13_task_summary = task_PyOpr(
        task_id="Strategy_13_task_summary",
        callable_func=strategy_13_task_summary_agent,
    )

    Strategy_13_overview = task_PyOpr(
        task_id="Strategy_13_overview",
        callable_func=strategy_13_overview_agent,
    )

    Strategy_14_a_1 = task_PyOpr(
        task_id="Strategy_14_a_1",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose current and anticipated changes to the entity’s business model, including its resource allocation, to address climate-related risks and opportunities (for example, these changes could include plans to manage or decommission carbon-, energy- or water-intensive operations; resource allocations resulting from demand or supply-chain changes; resource allocations arising from business development through capital expenditure or additional expenditure on research and development; and acquisitions or divestments)?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_14_a_2 = task_PyOpr(
        task_id="Strategy_14_a_2",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose current and anticipated direct mitigation and adaptation efforts (for example, through changes in production processes or equipment, relocation of facilities, workforce adjustments, and changes in product specifications)?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_14_a_3 = task_PyOpr(
        task_id="Strategy_14_a_3",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose any climate-related transition plan the entity has, including information about key assumptions used in developing its transition plan, and dependencies on which the entity’s transition plan relies?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_14_a_4 = task_PyOpr(
        task_id="Strategy_14_a_4",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose how the entity plans to achieve any climate-related targets, including any greenhouse gas emissions targets?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_14_a_task_summary = task_PyOpr(
        task_id="Strategy_14_a_task_summary",
        callable_func=strategy_14_a_task_summary_agent,
    )

    Strategy_14_a_overview = task_PyOpr(
        task_id="Strategy_14_a_overview",
        callable_func=strategy_14_a_overview_agent,
    )

    Strategy_14_b = task_PyOpr(
        task_id="Strategy_14_b",
        callable_func=strategy_14_b_agent,
    )

    Strategy_14_c = task_PyOpr(
        task_id="Strategy_14_c",
        callable_func=strategy_14_c_agent,
    )

    Strategy_14_overview = task_PyOpr(
        task_id="Strategy_14_overview",
        callable_func=strategy_14_overview_agent,
    )

    Strategy_15_a = task_PyOpr(
        task_id="Strategy_15_a",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose information that enables users of general purpose financial reports to understand the effects of climate-related risks and opportunities on the entity’s financial position, financial performance and cash flows for the reporting period (current financial effects)?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_15_b = task_PyOpr(
        task_id="Strategy_15_b",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose information that enables users of general purpose financial reports to understand the anticipated effects of climate-related risks and opportunities on the entity’s financial position, financial performance and cash flows over the short, medium and long term, taking into consideration how climate-related risks and opportunities are included in the entity’s financial planning (anticipated financial effects)?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_15_task_summary = task_PyOpr(
        task_id="Strategy_15_task_summary",
        callable_func=strategy_15_task_summary_agent,
    )

    Strategy_15_overview = task_PyOpr(
        task_id="Strategy_15_overview",
        callable_func=strategy_15_overview_agent,
    )

    Strategy_16_a = task_PyOpr(
        task_id="Strategy_16_a",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose quantitative and qualitative information about: how climate-related risks and opportunities have affected its financial position, financial performance and cash flows for the reporting period?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_16_b = task_PyOpr(
        task_id="Strategy_16_b",
        callable_func=strategy_16_b_agent,
    )

    Strategy_16_c_1 = task_PyOpr(
        task_id="Strategy_16_c_1",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose quantitative and qualitative information about: how the entity expects its financial position to change over the short, medium and long term, given its strategy to manage climate-related risks and opportunities, taking into consideration its investment and disposal plans (for example, plans for capital expenditure, major acquisitions and divestments, joint ventures, business transformation, innovation, new business areas, and asset retirements), including plans the entity is not contractually committed to?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_16_c_2 = task_PyOpr(
        task_id="Strategy_16_c_2",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose quantitative and qualitative information about: how the entity expects its financial position to change over the short, medium and long term, given its strategy to manage climate-related risks and opportunities, taking into consideration its planned sources of funding to implement its strategy?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_16_d = task_PyOpr(
        task_id="Strategy_16_d",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report disclose quantitative and qualitative information about: how the entity expects its financial performance and cash flows to change over the short, medium and long term, given its strategy to manage climate-related risks and opportunities (for example, increased revenue from products and services aligned with a lower-carbon economy; costs arising from physical damage to assets from climate events; and expenses associated with climate adaptation or mitigation)?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_16_task_summary = task_PyOpr(
        task_id="Strategy_16_task_summary",
        callable_func=strategy_16_task_summary_agent,
    )

    Strategy_16_overview = task_PyOpr(
        task_id="Strategy_16_overview",
        callable_func=strategy_16_overview_agent,
    )

    Strategy_18_a = task_PyOpr(
        task_id="Strategy_18_a",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report use all reasonable and supportable information that is available to the entity at the reporting date without undue cost or effort, in preparing disclosures about the anticipated financial effects of a climate- related risk or opportunity?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_18_b = task_PyOpr(
        task_id="Strategy_18_b",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report use an approach that is commensurate with the skills, capabilities and resources that are available to the entity for preparing those disclosures about the anticipated financial effects of a climate- related risk or opportunity?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_18_task_summary = task_PyOpr(
        task_id="Strategy_18_task_summary",
        callable_func=strategy_18_task_summary_agent,
    )

    Strategy_18_overview = task_PyOpr(
        task_id="Strategy_18_overview",
        callable_func=strategy_18_overview_agent,
    )

    Strategy_19_a = task_PyOpr(
        task_id="Strategy_19_a",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report claim that the current or anticipated financial effects of a climate-related risk or opportunity are not separately identifiable?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_19_b = task_PyOpr(
        task_id="Strategy_19_b",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report claim that the level of measurement uncertainty involved in estimating those effects (the current or anticipated financial effects of a climate-related risk or opportunity) is so high that the resulting quantitative information would not be useful?"
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_19_task_summary = task_PyOpr(
        task_id="Strategy_19_task_summary",
        callable_func=strategy_19_task_summary_agent,
    )

    Strategy_19_overview = task_PyOpr(
        task_id="Strategy_19_overview",
        callable_func=strategy_19_overview_agent,
    )

    Strategy_20 = task_PyOpr(
        task_id="Strategy_20",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report claim that the entity does not have the skills, capabilities or resources to provide that quantitative information about the anticipated financial effects of a climate-related risk or opportunity? "
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_20_task_summary = task_PyOpr(
        task_id="Strategy_20_task_summary",
        callable_func=strategy_20_task_summary_agent,
    )

    determine_path = task_PyOpr(
        task_id="determine_path",
        callable_func=determine_path_agent,
    )

    branch_task = BranchPythonOperator(
        task_id="branch_task",
        python_callable=determine_branch,
    )

    Strategy_21_a = task_PyOpr(
        task_id="Strategy_21_a",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report explain why it has not provided quantitative information about the anticipated financial effects of a climate-related risk or opportunity? "
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_21_b = task_PyOpr(
        task_id="Strategy_21_b",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report provide qualitative information about those financial effects, including identifying line items, totals and subtotals within the related financial statements that are likely to be affected, or have been affected, by that climate-related risk or opportunity? "
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_21_c = task_PyOpr(
        task_id="Strategy_21_c",
        callable_func=agent,
        op_kwargs={
            "data_to_send": {
                "input": {
                    "input": "Does the report provide quantitative information about the combined financial effects of that climate-related risk or opportunity with other climate-related risks or opportunities and other factors unless the entity determines that quantitative information about the combined financial effects would not be useful? "
                },
                "config": {"configurable": {"session_id": session_id}},
            }
        },
    )

    Strategy_overview = task_PyOpr(
        task_id="Strategy_overview",
        callable_func=strategy_13_overview_agent,
    )

    results_merge = PythonOperator(
        task_id="merge",
        python_callable=merge,
    )

    translate = task_PyOpr(
        task_id="translate",
        callable_func=translate_agent,
    )

    save_file_task = task_PyOpr(
        task_id="save_file",
        callable_func=save_file,
    )

    (
        [
            Governance_6_a_1,
            Governance_6_a_2,
            Governance_6_a_3,
            Governance_6_a_4,
            Governance_6_a_5,
        ]
        >> Governance_6_a_task_summary
        >> Governance_6_a_overview
    )

    (
        [
            Governance_6_b_1,
            Governance_6_b_2,
        ]
        >> Governance_6_b_task_summary
        >> Governance_6_b_overview
    )

    [Governance_6_a_overview, Governance_6_b_overview] >> Governance_overview

    (
        [
            Strategy_10_a,
            Strategy_10_b,
            Strategy_10_c,
            Strategy_10_d,
        ]
        >> Strategy_10_task_summary
        >> Strategy_10_overview
    )

    Strategy_11 >> Strategy_11_overview

    [Strategy_13_a, Strategy_13_b] >> Strategy_13_task_summary >> Strategy_13_overview

    (
        [Strategy_14_a_1, Strategy_14_a_2, Strategy_14_a_3, Strategy_14_a_4]
        >> Strategy_14_a_task_summary
        >> Strategy_14_a_overview
        >> Strategy_14_b
    )
    Strategy_14_a_overview >> Strategy_14_c
    [Strategy_14_a_overview, Strategy_14_b, Strategy_14_c] >> Strategy_14_overview
    [Strategy_15_a, Strategy_15_b] >> Strategy_15_task_summary >> Strategy_15_overview
    Strategy_16_a >> Strategy_16_b
    (
        [Strategy_16_a, Strategy_16_b, Strategy_16_c_1, Strategy_16_c_2, Strategy_16_d]
        >> Strategy_16_task_summary
        >> Strategy_16_overview
    )
    [Strategy_18_a, Strategy_18_b] >> Strategy_18_task_summary >> Strategy_18_overview
    [Strategy_19_a, Strategy_19_b] >> Strategy_19_task_summary >> Strategy_19_overview
    Strategy_20 >> Strategy_20_task_summary
    (
        [Strategy_19_overview, Strategy_20_task_summary]
        >> determine_path
        >> branch_task
        >> [Strategy_21_a, Strategy_21_b, Strategy_21_c]
    )

    [
        Strategy_10_overview,
        Strategy_11_overview,
        Strategy_13_overview,
        Strategy_14_overview,
        Strategy_15_overview,
        Strategy_16_overview,
        Strategy_18_overview,
        Strategy_19_overview,
    ] >> Strategy_overview

    (
        [
            Governance_overview,
            Governance_6_a_overview,
            Governance_6_a_task_summary,
            Governance_6_b_overview,
            Governance_6_b_task_summary,
            Strategy_overview,
            Strategy_10_overview,
            Strategy_10_task_summary,
            Strategy_11_overview,
            Strategy_13_overview,
            Strategy_13_task_summary,
        ]
        >> results_merge
        >> translate
        >> save_file_task
    )