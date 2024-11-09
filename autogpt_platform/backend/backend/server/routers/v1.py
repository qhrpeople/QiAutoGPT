import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Annotated, Any, Dict, Sequence

from autogpt_libs.auth.middleware import auth_middleware
from autogpt_libs.utils.cache import thread_cached
from fastapi import APIRouter, Body, Depends, HTTPException
from typing_extensions import TypedDict

import backend.data.block
import backend.server.integrations.router
import backend.server.routers.analytics
from backend.data import execution as execution_db
from backend.data import graph as graph_db
from backend.data.block import BlockInput, CompletedBlockOutput
from backend.data.credit import get_block_costs, get_user_credit_model
from backend.data.user import get_or_create_user
from backend.executor import ExecutionManager, ExecutionScheduler
from backend.integrations.creds_manager import IntegrationCredentialsManager
from backend.integrations.webhooks.graph_lifecycle_hooks import (
    on_graph_activate,
    on_graph_deactivate,
)
from backend.server.model import CreateGraph, SetGraphActiveVersion
from backend.server.utils import get_user_id
from backend.util.service import get_service_client
from backend.util.settings import Settings

if TYPE_CHECKING:
    from autogpt_libs.supabase_integration_credentials_store.types import Credentials


@thread_cached
def execution_manager_client() -> ExecutionManager:
    return get_service_client(ExecutionManager)


@thread_cached
def execution_scheduler_client() -> ExecutionScheduler:
    return get_service_client(ExecutionScheduler)


settings = Settings()
logger = logging.getLogger(__name__)
integration_creds_manager = IntegrationCredentialsManager()


_user_credit_model = get_user_credit_model()

# Define the API routes
v1_router = APIRouter(prefix="/api")


v1_router.include_router(
    backend.server.integrations.router.router,
    prefix="/integrations",
    tags=["integrations"],
)

v1_router.include_router(
    backend.server.routers.analytics.router,
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(auth_middleware)],
)


########################################################
##################### Auth #############################
########################################################


@v1_router.post("/auth/user", tags=["auth"], dependencies=[Depends(auth_middleware)])
async def get_or_create_user_route(user_data: dict = Depends(auth_middleware)):
    user = await get_or_create_user(user_data)
    return user.model_dump()


########################################################
##################### Blocks ###########################
########################################################


@v1_router.get(path="/blocks", tags=["blocks"], dependencies=[Depends(auth_middleware)])
def get_graph_blocks() -> Sequence[dict[Any, Any]]:
    blocks = [block() for block in backend.data.block.get_blocks().values()]
    costs = get_block_costs()
    return [{**b.to_dict(), "costs": costs.get(b.id, [])} for b in blocks]


@v1_router.post(
    path="/blocks/{block_id}/execute",
    tags=["blocks"],
    dependencies=[Depends(auth_middleware)],
)
def execute_graph_block(block_id: str, data: BlockInput) -> CompletedBlockOutput:
    obj = backend.data.block.get_block(block_id)
    if not obj:
        raise HTTPException(status_code=404, detail=f"Block #{block_id} not found.")

    output = defaultdict(list)
    for name, data in obj.execute(data):
        output[name].append(data)
    return output


########################################################
##################### Credits ##########################
########################################################


@v1_router.get(path="/credits", dependencies=[Depends(auth_middleware)])
async def get_user_credits(
    user_id: Annotated[str, Depends(get_user_id)]
) -> dict[str, int]:
    return {"credits": await _user_credit_model.get_or_refill_credit(user_id)}


########################################################
##################### Graphs ###########################
########################################################


class DeleteGraphResponse(TypedDict):
    version_counts: int


@v1_router.get(path="/graphs", tags=["graphs"], dependencies=[Depends(auth_middleware)])
async def get_graphs(
    user_id: Annotated[str, Depends(get_user_id)],
    with_runs: bool = False,
) -> Sequence[graph_db.GraphMeta]:
    return await graph_db.get_graphs_meta(
        include_executions=with_runs, filter_by="active", user_id=user_id
    )


@v1_router.get(
    path="/graphs/{graph_id}", tags=["graphs"], dependencies=[Depends(auth_middleware)]
)
@v1_router.get(
    path="/graphs/{graph_id}/versions/{version}",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def get_graph(
    graph_id: str,
    user_id: Annotated[str, Depends(get_user_id)],
    version: int | None = None,
    hide_credentials: bool = False,
) -> graph_db.Graph:
    graph = await graph_db.get_graph(
        graph_id, version, user_id=user_id, hide_credentials=hide_credentials
    )
    if not graph:
        raise HTTPException(status_code=404, detail=f"Graph #{graph_id} not found.")
    return graph


@v1_router.get(
    path="/graphs/{graph_id}/versions",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
@v1_router.get(
    path="/templates/{graph_id}/versions",
    tags=["templates", "graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def get_graph_all_versions(
    graph_id: str, user_id: Annotated[str, Depends(get_user_id)]
) -> Sequence[graph_db.Graph]:
    graphs = await graph_db.get_graph_all_versions(graph_id, user_id=user_id)
    if not graphs:
        raise HTTPException(status_code=404, detail=f"Graph #{graph_id} not found.")
    return graphs


@v1_router.post(
    path="/graphs", tags=["graphs"], dependencies=[Depends(auth_middleware)]
)
async def create_new_graph(
    create_graph: CreateGraph, user_id: Annotated[str, Depends(get_user_id)]
) -> graph_db.Graph:
    return await do_create_graph(create_graph, is_template=False, user_id=user_id)


async def do_create_graph(
    create_graph: CreateGraph,
    is_template: bool,
    # user_id doesn't have to be annotated like on other endpoints,
    # because create_graph isn't used directly as an endpoint
    user_id: str,
) -> graph_db.Graph:
    if create_graph.graph:
        graph = graph_db.make_graph_model(create_graph.graph, user_id)
    elif create_graph.template_id:
        # Create a new graph from a template
        graph = await graph_db.get_graph(
            create_graph.template_id,
            create_graph.template_version,
            template=True,
            user_id=user_id,
        )
        if not graph:
            raise HTTPException(
                400, detail=f"Template #{create_graph.template_id} not found"
            )
        graph.version = 1
    else:
        raise HTTPException(
            status_code=400, detail="Either graph or template_id must be provided."
        )

    graph.is_template = is_template
    graph.is_active = not is_template
    graph.reassign_ids(reassign_graph_id=True)

    graph = await graph_db.create_graph(graph, user_id=user_id)
    graph = await on_graph_activate(
        graph,
        get_credentials=lambda id: integration_creds_manager.get(user_id, id),
    )
    return graph


@v1_router.delete(
    path="/graphs/{graph_id}", tags=["graphs"], dependencies=[Depends(auth_middleware)]
)
async def delete_graph(
    graph_id: str, user_id: Annotated[str, Depends(get_user_id)]
) -> DeleteGraphResponse:
    return {"version_counts": await graph_db.delete_graph(graph_id, user_id=user_id)}


@v1_router.put(
    path="/graphs/{graph_id}", tags=["graphs"], dependencies=[Depends(auth_middleware)]
)
@v1_router.put(
    path="/templates/{graph_id}",
    tags=["templates", "graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def update_graph(
    graph_id: str,
    graph: graph_db.Graph,
    user_id: Annotated[str, Depends(get_user_id)],
) -> graph_db.Graph:
    # Sanity check
    if graph.id and graph.id != graph_id:
        raise HTTPException(400, detail="Graph ID does not match ID in URI")

    # Determine new version
    existing_versions = await graph_db.get_graph_all_versions(graph_id, user_id=user_id)
    if not existing_versions:
        raise HTTPException(404, detail=f"Graph #{graph_id} not found")
    latest_version_number = max(g.version for g in existing_versions)
    graph.version = latest_version_number + 1

    latest_version_graph = next(
        v for v in existing_versions if v.version == latest_version_number
    )
    current_active_version = next((v for v in existing_versions if v.is_active), None)
    if latest_version_graph.is_template != graph.is_template:
        raise HTTPException(
            400, detail="Changing is_template on an existing graph is forbidden"
        )
    graph.is_active = not graph.is_template
    graph = graph_db.make_graph_model(graph, user_id)
    graph.reassign_ids()

    new_graph_version = await graph_db.create_graph(graph, user_id=user_id)

    if new_graph_version.is_active:

        def get_credentials(credentials_id: str) -> "Credentials | None":
            return integration_creds_manager.get(user_id, credentials_id)

        # Handle activation of the new graph first to ensure continuity
        new_graph_version = await on_graph_activate(
            new_graph_version,
            get_credentials=get_credentials,
        )
        # Ensure new version is the only active version
        await graph_db.set_graph_active_version(
            graph_id=graph_id, version=new_graph_version.version, user_id=user_id
        )
        if current_active_version:
            # Handle deactivation of the previously active version
            await on_graph_deactivate(
                current_active_version,
                get_credentials=get_credentials,
            )

    return new_graph_version


@v1_router.put(
    path="/graphs/{graph_id}/versions/active",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def set_graph_active_version(
    graph_id: str,
    request_body: SetGraphActiveVersion,
    user_id: Annotated[str, Depends(get_user_id)],
):
    new_active_version = request_body.active_graph_version
    new_active_graph = await graph_db.get_graph(
        graph_id, new_active_version, user_id=user_id
    )
    if not new_active_graph:
        raise HTTPException(404, f"Graph #{graph_id} v{new_active_version} not found")

    current_active_graph = await graph_db.get_graph(graph_id, user_id=user_id)

    def get_credentials(credentials_id: str) -> "Credentials | None":
        return integration_creds_manager.get(user_id, credentials_id)

    # Handle activation of the new graph first to ensure continuity
    await on_graph_activate(
        new_active_graph,
        get_credentials=get_credentials,
    )
    # Ensure new version is the only active version
    await graph_db.set_graph_active_version(
        graph_id=graph_id,
        version=new_active_version,
        user_id=user_id,
    )
    if current_active_graph and current_active_graph.version != new_active_version:
        # Handle deactivation of the previously active version
        await on_graph_deactivate(
            current_active_graph,
            get_credentials=get_credentials,
        )


@v1_router.post(
    path="/graphs/{graph_id}/execute",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def execute_graph(
    graph_id: str,
    node_input: dict[Any, Any],
    user_id: Annotated[str, Depends(get_user_id)],
) -> dict[str, Any]:  # FIXME: add proper return type
    try:
        graph_exec = execution_manager_client().add_execution(
            graph_id, node_input, user_id=user_id
        )
        return {"id": graph_exec["graph_exec_id"]}
    except Exception as e:
        msg = e.__str__().encode().decode("unicode_escape")
        raise HTTPException(status_code=400, detail=msg)


@v1_router.post(
    path="/graphs/{graph_id}/executions/{graph_exec_id}/stop",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def stop_graph_run(
    graph_exec_id: str, user_id: Annotated[str, Depends(get_user_id)]
) -> Sequence[execution_db.ExecutionResult]:
    if not await execution_db.get_graph_execution(graph_exec_id, user_id):
        raise HTTPException(404, detail=f"Agent execution #{graph_exec_id} not found")

    await asyncio.to_thread(
        lambda: execution_manager_client().cancel_execution(graph_exec_id)
    )

    # Retrieve & return canceled graph execution in its final state
    return await execution_db.get_execution_results(graph_exec_id)


@v1_router.get(
    path="/graphs/{graph_id}/input_schema",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def get_graph_input_schema(
    graph_id: str,
    user_id: Annotated[str, Depends(get_user_id)],
) -> Sequence[graph_db.InputSchemaItem]:
    try:
        graph = await graph_db.get_graph(graph_id, user_id=user_id)
        return graph.get_input_schema() if graph else []
    except Exception:
        raise HTTPException(status_code=404, detail=f"Graph #{graph_id} not found.")


@v1_router.get(
    path="/graphs/{graph_id}/executions",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def list_graph_runs(
    graph_id: str,
    user_id: Annotated[str, Depends(get_user_id)],
    graph_version: int | None = None,
) -> Sequence[str]:
    graph = await graph_db.get_graph(graph_id, graph_version, user_id=user_id)
    if not graph:
        rev = "" if graph_version is None else f" v{graph_version}"
        raise HTTPException(
            status_code=404, detail=f"Agent #{graph_id}{rev} not found."
        )

    return await execution_db.list_executions(graph_id, graph_version)


@v1_router.get(
    path="/graphs/{graph_id}/executions/{graph_exec_id}",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def get_graph_run_node_execution_results(
    graph_id: str,
    graph_exec_id: str,
    user_id: Annotated[str, Depends(get_user_id)],
) -> Sequence[execution_db.ExecutionResult]:
    graph = await graph_db.get_graph(graph_id, user_id=user_id)
    if not graph:
        raise HTTPException(status_code=404, detail=f"Graph #{graph_id} not found.")

    return await execution_db.get_execution_results(graph_exec_id)


# NOTE: This is used for testing
async def get_graph_run_status(
    graph_id: str,
    graph_exec_id: str,
    user_id: Annotated[str, Depends(get_user_id)],
) -> execution_db.ExecutionStatus:
    graph = await graph_db.get_graph(graph_id, user_id=user_id)
    if not graph:
        raise HTTPException(status_code=404, detail=f"Graph #{graph_id} not found.")

    execution = await execution_db.get_graph_execution(graph_exec_id, user_id)
    if not execution:
        raise HTTPException(
            status_code=404, detail=f"Execution #{graph_exec_id} not found."
        )

    return execution.executionStatus


########################################################
##################### Templates ########################
########################################################


@v1_router.get(
    path="/templates",
    tags=["graphs", "templates"],
    dependencies=[Depends(auth_middleware)],
)
async def get_templates(
    user_id: Annotated[str, Depends(get_user_id)]
) -> Sequence[graph_db.GraphMeta]:
    return await graph_db.get_graphs_meta(filter_by="template", user_id=user_id)


@v1_router.get(
    path="/templates/{graph_id}",
    tags=["templates", "graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def get_template(graph_id: str, version: int | None = None) -> graph_db.Graph:
    graph = await graph_db.get_graph(graph_id, version, template=True)
    if not graph:
        raise HTTPException(status_code=404, detail=f"Template #{graph_id} not found.")
    return graph


@v1_router.post(
    path="/templates",
    tags=["templates", "graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def create_new_template(
    create_graph: CreateGraph, user_id: Annotated[str, Depends(get_user_id)]
) -> graph_db.Graph:
    return await do_create_graph(create_graph, is_template=True, user_id=user_id)


########################################################
##################### Schedules ########################
########################################################


@v1_router.post(
    path="/graphs/{graph_id}/schedules",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def create_schedule(
    graph_id: str,
    cron: str,
    input_data: dict[Any, Any],
    user_id: Annotated[str, Depends(get_user_id)],
) -> dict[Any, Any]:
    graph = await graph_db.get_graph(graph_id, user_id=user_id)
    if not graph:
        raise HTTPException(status_code=404, detail=f"Graph #{graph_id} not found.")

    return {
        "id": await asyncio.to_thread(
            lambda: execution_scheduler_client().add_execution_schedule(
                graph_id=graph_id,
                graph_version=graph.version,
                cron=cron,
                input_data=input_data,
                user_id=user_id,
            )
        )
    }


@v1_router.put(
    path="/graphs/schedules/{schedule_id}",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def update_schedule(
    schedule_id: str,
    input_data: dict[Any, Any],
    user_id: Annotated[str, Depends(get_user_id)],
) -> dict[Any, Any]:
    is_enabled = input_data.get("is_enabled", False)
    execution_scheduler_client().update_schedule(
        schedule_id, is_enabled, user_id=user_id
    )
    return {"id": schedule_id}


@v1_router.get(
    path="/graphs/{graph_id}/schedules",
    tags=["graphs"],
    dependencies=[Depends(auth_middleware)],
)
async def get_execution_schedules(
    graph_id: str, user_id: Annotated[str, Depends(get_user_id)]
) -> dict[str, str]:
    return execution_scheduler_client().get_execution_schedules(graph_id, user_id)


########################################################
##################### Settings ########################
########################################################


@v1_router.post(
    path="/settings", tags=["settings"], dependencies=[Depends(auth_middleware)]
)
async def update_configuration(
    updated_settings: Annotated[
        Dict[str, Any],
        Body(
            examples=[
                {
                    "config": {
                        "num_graph_workers": 10,
                        "num_node_workers": 10,
                    }
                }
            ]
        ),
    ],
):
    settings = Settings()
    try:
        updated_fields: dict[Any, Any] = {"config": [], "secrets": []}
        for key, value in updated_settings.get("config", {}).items():
            if hasattr(settings.config, key):
                setattr(settings.config, key, value)
                updated_fields["config"].append(key)
        for key, value in updated_settings.get("secrets", {}).items():
            if hasattr(settings.secrets, key):
                setattr(settings.secrets, key, value)
                updated_fields["secrets"].append(key)
        settings.save()
        return {
            "message": "Settings updated successfully",
            "updated_fields": updated_fields,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
