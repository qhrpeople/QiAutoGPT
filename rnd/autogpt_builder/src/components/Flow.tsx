"use client";
import React, {
  useState,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  MouseEvent,
  createContext,
} from "react";
import { shallow } from "zustand/vanilla/shallow";
import {
  ReactFlow,
  ReactFlowProvider,
  Controls,
  Background,
  Node,
  Edge,
  OnConnect,
  NodeTypes,
  Connection,
  EdgeTypes,
  MarkerType,
  NodeChange,
  EdgeChange,
  useStore,
  useReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  useUpdateNodeInternals,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { CustomNode, CustomNodeData } from "./CustomNode";
import "./flow.css";
import AutoGPTServerAPI, {
  Block,
  BlockIOSubSchema,
  Graph,
  Link,
  NodeExecutionResult,
} from "@/lib/autogpt-server-api";
import {
  deepEquals,
  getTypeColor,
  removeEmptyStringsAndNulls,
  setNestedProperty,
} from "@/lib/utils";
import { history } from "./history";
import { CustomEdge, CustomEdgeData } from "./CustomEdge";
import ConnectionLine from "./ConnectionLine";
import Ajv from "ajv";
import { Control, ControlPanel } from "@/components/edit/control/ControlPanel";
import { SaveControl } from "@/components/edit/control/SaveControl";
import { BlocksControl } from "@/components/edit/control/BlocksControl";
import { IconPlay, IconRedo2, IconUndo2 } from "@/components/ui/icons";

// This is for the history, this is the minimum distance a block must move before it is logged
// It helps to prevent spamming the history with small movements especially when pressing on a input in a block
const MINIMUM_MOVE_BEFORE_LOG = 50;

const ajv = new Ajv({ strict: false, allErrors: true });

type FlowContextType = {
  visualizeBeads: "no" | "static" | "animate";
};

export const FlowContext = createContext<FlowContextType | null>(null);

const FlowEditor: React.FC<{
  flowID?: string;
  template?: boolean;
  className?: string;
}> = ({ flowID, template, className }) => {
  // const { _setNodes, _setEdges } = useStore(
  //   useCallback(
  //     ({ setRootNodes, setRootEdges }) => ({
  //       _setNodes: setRootNodes,
  //       _setEdges: setRootEdges,
  //     }),
  //     [],
  //   ),
  //   shallow,
  // );
  const {
    addNodes,
    addEdges,
    getNode,
    getNodes,
    getEdges,
    // setRootNodes,
    // setRootEdges,
    deleteElements,
    updateNode,
    updateEdge,
    updateNodeData,
    updateEdgeData,
  } = useReactFlow<CustomNode, CustomEdge>();
  const [nodeId, setNodeId] = useState<number>(1);
  const [availableNodes, setAvailableNodes] = useState<Block[]>([]);
  const [savedAgent, setSavedAgent] = useState<Graph | null>(null);
  const [agentDescription, setAgentDescription] = useState<string>("");
  const [agentName, setAgentName] = useState<string>("");
  const [copiedNodes, setCopiedNodes] = useState<CustomNode[]>([]);
  const [copiedEdges, setCopiedEdges] = useState<CustomEdge[]>([]);
  const [isAnyModalOpen, setIsAnyModalOpen] = useState(false); // Track if any modal is open
  const [visualizeBeads, setVisualizeBeads] = useState<
    "no" | "static" | "animate"
  >("animate");
  const [nodes, setRootNodes] = useState<CustomNode[]>([]);
  const [edges, setRootEdges] = useState<CustomEdge[]>([]);

  const apiUrl = process.env.NEXT_PUBLIC_AGPT_SERVER_URL!;
  const api = useMemo(() => new AutoGPTServerAPI(apiUrl), [apiUrl]);
  const initialPositionRef = useRef<{
    [key: string]: { x: number; y: number };
  }>({});
  const isDragging = useRef(false);

  useEffect(() => {
    api
      .connectWebSocket()
      .then(() => {
        console.log("WebSocket connected");
        api.onWebSocketMessage("execution_event", (data) => {
          updateNodesWithExecutionData([data]);
        });
      })
      .catch((error) => {
        console.error("Failed to connect WebSocket:", error);
      });

    return () => {
      api.disconnectWebSocket();
    };
  }, [api]);

  useEffect(() => {
    api
      .getBlocks()
      .then((blocks) => setAvailableNodes(blocks))
      .catch();
  }, []);

  // Load existing graph
  useEffect(() => {
    if (!flowID || availableNodes.length == 0) return;

    (template ? api.getTemplate(flowID) : api.getGraph(flowID)).then((graph) =>
      loadGraph(graph),
    );
  }, [flowID, template, availableNodes]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const isMac = navigator.platform.toUpperCase().indexOf("MAC") >= 0;
      const isUndo =
        (isMac ? event.metaKey : event.ctrlKey) && event.key === "z";
      const isRedo =
        (isMac ? event.metaKey : event.ctrlKey) &&
        (event.key === "y" || (event.shiftKey && event.key === "Z"));

      if (isUndo) {
        event.preventDefault();
        handleUndo();
      }

      if (isRedo) {
        event.preventDefault();
        handleRedo();
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  const onNodeDragStart = (_: MouseEvent, node: Node) => {
    initialPositionRef.current[node.id] = { ...node.position };
    isDragging.current = true;
  };

  const onNodeDragEnd = (_: MouseEvent, node: Node | null) => {
    if (!node) return;

    isDragging.current = false;
    const oldPosition = initialPositionRef.current[node.id];
    const newPosition = node.position;

    // Calculate the movement distance
    if (!oldPosition || !newPosition) return;

    const distanceMoved = Math.sqrt(
      Math.pow(newPosition.x - oldPosition.x, 2) +
      Math.pow(newPosition.y - oldPosition.y, 2),
    );

    if (distanceMoved > MINIMUM_MOVE_BEFORE_LOG) {
      // Minimum movement threshold
      history.push({
        type: "UPDATE_NODE_POSITION",
        payload: { nodeId: node.id, oldPosition, newPosition },
        undo: () =>
          updateNode(node.id, { position: oldPosition }),
        redo: () =>
          updateNode(node.id, { position: newPosition }),
      });
    }
    delete initialPositionRef.current[node.id];
  };

  const getOutputType = (id: string, handleId: string) => {
    const node = getNode(id);
    if (!node) return "unknown";

    const outputSchema = node.data.outputSchema;
    if (!outputSchema) return "unknown";

    const outputHandle = outputSchema.properties[handleId];
    if (!("type" in outputHandle)) return "unknown";
    return outputHandle.type;
  };

  // Function to clear status, output, and close the output info dropdown of all nodes
  // and reset data beads on edges
  const clearNodesStatusAndOutput = useCallback(() => {
    setRootNodes((nds) => {
      const newNodes = nds.map((node) => ({
        ...node,
        data: {
          ...node.data,
          status: undefined,
          output_data: undefined,
          isOutputOpen: false, // Close the output info dropdown
        },
      }));

      return newNodes;
    });
  }, [setRootNodes]);

  const onNodesChange = useCallback(
    (nodeChanges: NodeChange<CustomNode>[]) => {
      // Persist the changes
      setRootNodes(prev => applyNodeChanges(nodeChanges, prev));

      // Remove all edges that were connected to deleted nodes
      nodeChanges
        .filter((change) => change.type == "remove")
        .forEach((deletedNode) => {
          const nodeID = deletedNode.id;

          const connectedEdges = edges.filter((edge) =>
            [edge.source, edge.target].includes(nodeID),
          );
          deleteElements({
            edges: connectedEdges.map((edge) => ({ id: edge.id })),
          });
        });
    },
    // [getNodes, getEdges, _setNodes, deleteElements],
    [deleteElements],
  );

  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      const edgeColor = getTypeColor(
        getOutputType(connection.source!, connection.sourceHandle!),
      );
      const sourcePos = getNode(connection.source!)?.position;
      console.log("sourcePos", sourcePos);
      const newEdge: CustomEdge = {
        id: formatEdgeID(connection),
        type: "custom",
        markerEnd: {
          type: MarkerType.ArrowClosed,
          strokeWidth: 2,
          color: edgeColor,
        },
        data: { edgeColor, sourcePos },
        ...connection,
        source: connection.source!,
        target: connection.target!,
      };

      addEdges(newEdge);
      history.push({
        type: "ADD_EDGE",
        payload: { edge: newEdge },
        undo: () => {
          deleteElements({ edges: [{ id: newEdge.id }] });
        },
        redo: () => {
          addEdges(newEdge);
        },
      });
      clearNodesStatusAndOutput(); // Clear status and output on connection change
    },
    [getNode, addEdges, history, deleteElements, clearNodesStatusAndOutput],
  );

  const onEdgesChange = useCallback(
    (edgeChanges: EdgeChange<CustomEdge>[]) => {
      // Persist the changes
      setRootEdges(prev => applyEdgeChanges(edgeChanges, prev));

      // Propagate edge changes to node data
      const addedEdges = edgeChanges.filter((change) => change.type === "add"),
        replaceEdges = edgeChanges.filter((change) => change.type === "replace"),
        removedEdges = edgeChanges.filter((change) => change.type === "remove"),
        selectedEdges = edgeChanges.filter((change) => change.type === "select");

      if (addedEdges.length > 0 || removedEdges.length > 0) {
        setRootNodes((nds) => {
          const newNodes = nds.map((node) => ({
            ...node,
            data: {
              ...node.data,
              connections: [
                // Remove node connections for deleted edges
                ...node.data.connections.filter(
                  (conn) =>
                    !removedEdges.some(
                      (removedEdge) => removedEdge.id === conn.edge_id,
                    ),
                ),
                // Add node connections for added edges
                ...addedEdges.map((addedEdge) => ({
                  edge_id: addedEdge.item.id,
                  source: addedEdge.item.source,
                  target: addedEdge.item.target,
                  sourceHandle: addedEdge.item.sourceHandle!,
                  targetHandle: addedEdge.item.targetHandle!,
                })),
              ],
            },
          }))

          return newNodes;
        });

        if (removedEdges.length > 0) {
          clearNodesStatusAndOutput(); // Clear status and output on edge deletion
        }
      }

      if (replaceEdges.length > 0) {
        // Reset node connections for all edges
        console.warn(
          "useReactFlow().setRootEdges was used to overwrite all edges. " +
          "Use addEdges, deleteElements, or reconnectEdge for incremental changes.",
          replaceEdges,
        );
        setRootNodes((nds) =>
          nds.map((node) => ({
            ...node,
            data: {
              ...node.data,
              connections: [
                ...replaceEdges.map((replaceEdge) => ({
                  edge_id: replaceEdge.item.id,
                  source: replaceEdge.item.source,
                  target: replaceEdge.item.target,
                  sourceHandle: replaceEdge.item.sourceHandle!,
                  targetHandle: replaceEdge.item.targetHandle!,
                })),
              ],
            },
          })),
        );
        clearNodesStatusAndOutput();
      }
    },
    // [getEdges, _setEdges, setRootNodes, clearNodesStatusAndOutput],
    [setRootNodes, clearNodesStatusAndOutput],
  );

  const addNode = useCallback(
    (blockId: string, nodeType: string) => {
      const nodeSchema = availableNodes.find((node) => node.id === blockId);
      if (!nodeSchema) {
        console.error(`Schema not found for block ID: ${blockId}`);
        return;
      }

      const newNode: CustomNode = {
        id: nodeId.toString(),
        type: "custom",
        position: { x: Math.random() * 400, y: Math.random() * 400 },
        data: {
          blockType: nodeType,
          title: `${nodeType} ${nodeId}`,
          description: nodeSchema.description,
          categories: nodeSchema.categories,
          inputSchema: nodeSchema.inputSchema,
          outputSchema: nodeSchema.outputSchema,
          hardcodedValues: {},
          setHardcodedValues: (values) => {
            updateNodeData(newNode.id, { hardcodedValues: values });
          },
          connections: [],
          isOutputOpen: false,
          block_id: blockId,
          setIsAnyModalOpen,
          setErrors: (errors: { [key: string]: string | null }) => {
            updateNodeData(newNode.id, { errors });
          },
        },
      };

      addNodes(newNode);
      setNodeId((prevId) => prevId + 1);
      clearNodesStatusAndOutput(); // Clear status and output when a new node is added

      history.push({
        type: "ADD_NODE",
        payload: { node: newNode.data },
        undo: () => deleteElements({ nodes: [{ id: newNode.id }] }),
        redo: () => addNodes(newNode),
      });
    },
    [
      nodeId,
      availableNodes,
      addNodes,
      setRootNodes,
      deleteElements,
      clearNodesStatusAndOutput,
    ],
  );

  const handleUndo = () => {
    history.undo();
  };

  const handleRedo = () => {
    history.redo();
  };

  function loadGraph(graph: Graph) {
    setSavedAgent(graph);
    setAgentName(graph.name);
    setAgentDescription(graph.description);

    setRootNodes(() => {
      const newNodes = graph.nodes.map((node) => {
        const block = availableNodes.find(
          (block) => block.id === node.block_id,
        )!;
        const newNode: CustomNode = {
          id: node.id,
          type: "custom",
          position: {
            x: node.metadata.position.x,
            y: node.metadata.position.y,
          },
          data: {
            block_id: block.id,
            blockType: block.name,
            categories: block.categories,
            description: block.description,
            title: `${block.name} ${node.id}`,
            inputSchema: block.inputSchema,
            outputSchema: block.outputSchema,
            hardcodedValues: node.input_default,
            setHardcodedValues: (values: { [key: string]: any }) => {
              setRootNodes((nds) =>
                nds.map((node) =>
                  node.id === newNode.id
                    ? {
                      ...node,
                      data: { ...node.data, hardcodedValues: values },
                    }
                    : node,
                ),
              );
            },
            connections: graph.links
              .filter((l) => [l.source_id, l.sink_id].includes(node.id))
              .map((link) => ({
                edge_id: formatEdgeID(link),
                source: link.source_id,
                sourceHandle: link.source_name,
                target: link.sink_id,
                targetHandle: link.sink_name,
              })),
            isOutputOpen: false,
            setIsAnyModalOpen,
            setErrors: (errors: { [key: string]: string | null }) => {
              setRootNodes((nds) =>
                nds.map((node) =>
                  node.id === newNode.id
                    ? { ...node, data: { ...node.data, errors } }
                    : node,
                ),
              );
            },
          },
        };
        return newNode;
      });
      setRootEdges(
        graph.links.map(
          (link) =>
          ({
            id: formatEdgeID(link),
            type: "custom",
            data: {
              edgeColor: getTypeColor(
                getOutputType(link.source_id, link.source_name!),
              ),
              sourcePos: getNode(link.source_id)?.position,
              beadUp: 0,
              beadDown: 0,
              beadData: [],
            },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              strokeWidth: 2,
              color: getTypeColor(
                getOutputType(link.source_id, link.source_name!),
              ),
            },
            source: link.source_id,
            target: link.sink_id,
            sourceHandle: link.source_name || undefined,
            targetHandle: link.sink_name || undefined,
          }),
        ),
      );
      return newNodes;
    });
  }

  const prepareNodeInputData = (node: CustomNode) => {
    console.log("Preparing input data for node:", node.id, node.data.blockType);

    const blockSchema = availableNodes.find(
      (n) => n.id === node.data.block_id,
    )?.inputSchema;

    if (!blockSchema) {
      console.error(`Schema not found for block ID: ${node.data.block_id}`);
      return {};
    }

    const getNestedData = (
      schema: BlockIOSubSchema,
      values: { [key: string]: any },
    ): { [key: string]: any } => {
      let inputData: { [key: string]: any } = {};

      if ("properties" in schema) {
        Object.keys(schema.properties).forEach((key) => {
          if (values[key] !== undefined) {
            if (
              "properties" in schema.properties[key] ||
              "additionalProperties" in schema.properties[key]
            ) {
              inputData[key] = getNestedData(
                schema.properties[key],
                values[key],
              );
            } else {
              inputData[key] = values[key];
            }
          }
        });
      }

      if ("additionalProperties" in schema) {
        inputData = { ...inputData, ...values };
      }

      return inputData;
    };

    let inputData = getNestedData(blockSchema, node.data.hardcodedValues);

    console.log(
      `Final prepared input for ${node.data.blockType} (${node.id}):`,
      inputData,
    );
    return inputData;
  };

  async function saveAgent(asTemplate: boolean = false) {
    setRootNodes((nds) =>
      nds.map((node) => ({
        ...node,
        data: {
          ...node.data,
          hardcodedValues: removeEmptyStringsAndNulls(
            node.data.hardcodedValues,
          ),
          status: undefined,
        },
      })),
    );
    // Reset bead count
    setRootEdges((edges) => {
      return edges.map(
        (edge) =>
        ({
          ...edge,
          data: {
            ...edge.data,
            beadUp: 0,
            beadDown: 0,
            beadData: [],
          },
        }),
      );
    });

    await new Promise((resolve) => setTimeout(resolve, 100));

    // const nodes = getNodes();
    // const edges = getEdges();
    console.log("All nodes before formatting:", nodes);
    const blockIdToNodeIdMap: Record<string, string> = {};

    const formattedNodes = nodes.map((node) => {
      nodes.forEach((node) => {
        const key = `${node.data.block_id}_${node.position.x}_${node.position.y}`;
        blockIdToNodeIdMap[key] = node.id;
      });
      const inputDefault = prepareNodeInputData(node);
      const inputNodes = edges
        .filter((edge) => edge.target === node.id)
        .map((edge) => ({
          name: edge.targetHandle || "",
          node_id: edge.source,
        }));

      const outputNodes = edges
        .filter((edge) => edge.source === node.id)
        .map((edge) => ({
          name: edge.sourceHandle || "",
          node_id: edge.target,
        }));

      return {
        id: node.id,
        block_id: node.data.block_id,
        input_default: inputDefault,
        input_nodes: inputNodes,
        output_nodes: outputNodes,
        data: {
          ...node.data,
          hardcodedValues: removeEmptyStringsAndNulls(
            node.data.hardcodedValues,
          ),
        },
        metadata: { position: node.position },
      };
    });

    const links = edges.map((edge) => ({
      source_id: edge.source,
      sink_id: edge.target,
      source_name: edge.sourceHandle || "",
      sink_name: edge.targetHandle || "",
    }));

    const payload = {
      id: savedAgent?.id!,
      name: agentName || "Agent Name",
      description: agentDescription || "Agent Description",
      nodes: formattedNodes,
      links: links, // Ensure this field is included
    };

    if (savedAgent && deepEquals(payload, savedAgent)) {
      console.debug("No need to save: Graph is the same as version on server");
      return;
    } else {
      console.debug(
        "Saving new Graph version; old vs new:",
        savedAgent,
        payload,
      );
    }

    const newSavedAgent = savedAgent
      ? await (savedAgent.is_template
        ? api.updateTemplate(savedAgent.id, payload)
        : api.updateGraph(savedAgent.id, payload))
      : await (asTemplate
        ? api.createTemplate(payload)
        : api.createGraph(payload));
    console.debug("Response from the API:", newSavedAgent);
    setSavedAgent(newSavedAgent);

    // Update the node IDs in the frontend
    // const updatedNodes = 

    setRootNodes((prev) => {
      return newSavedAgent.nodes
        .map((backendNode) => {
          const key = `${backendNode.block_id}_${backendNode.metadata.position.x}_${backendNode.metadata.position.y}`;
          const frontendNodeId = blockIdToNodeIdMap[key];
          const frontendNode = prev.find((node) => node.id === frontendNodeId);
          console.log(">> Updating node", frontendNodeId, frontendNode);
          console.log(">> Backend node", backendNode);

          return frontendNode
            ? {
              ...frontendNode,
              position: backendNode.metadata.position,
              data: {
                ...frontendNode.data,
                backend_id: backendNode.id,
              },
            }
            : null;
        })
        .filter((node) => node !== null);
    });

    return newSavedAgent.id;
  }

  const validateNodes = (): boolean => {
    console.log("Validating nodes");
    let isValid = true;

    nodes.forEach((node) => {
      const validate = ajv.compile(node.data.inputSchema);
      const errors = {} as { [key: string]: string | null };

      // Validate values against schema using AJV
      const valid = validate(node.data.hardcodedValues);
      if (!valid) {
        // Populate errors if validation fails
        validate.errors?.forEach((error) => {
          // Skip error if there's an edge connected
          const path =
            "dataPath" in error
              ? (error.dataPath as string)
              : error.instancePath;
          const handle = path.split(/[\/.]/)[0];
          if (
            node.data.connections.some(
              (conn) => conn.target === node.id || conn.targetHandle === handle,
            )
          ) {
            console.log("Skipping error for connected edge");
            return;
          }
          console.warn("Error", error);
          isValid = false;
          if (path && error.message) {
            const key = path.slice(1);
            console.log("Error", key, error.message);
            setNestedProperty(
              errors,
              key,
              error.message[0].toUpperCase() + error.message.slice(1),
            );
          } else if (error.keyword === "required") {
            const key = error.params.missingProperty;
            setNestedProperty(errors, key, "This field is required");
          }
        });
      }
      node.data.setErrors(errors);
    });

    return isValid;
  };

  const runAgent = async () => {
    try {
      const newAgentId = await saveAgent();
      if (!newAgentId) {
        console.error("Error saving agent; aborting run");
        return;
      }

      if (!validateNodes()) {
        console.error("Validation failed; aborting run");
        return;
      }

      api.subscribeToExecution(newAgentId);
      await api.executeGraph(newAgentId);
    } catch (error) {
      console.error("Error running agent:", error);
    }
  };

  function getFrontendId(backendId: string, nodes: CustomNode[]) {
    const node = nodes.find((node) => node.data.backend_id === backendId);
    return node?.id;
  }

  function updateEdgeBeads(
    executionData: NodeExecutionResult[],
    nodes: CustomNode[],
  ) {
    setRootEdges((edges) => {
      const newEdges = JSON.parse(
        JSON.stringify(edges),
      ) as CustomEdge[];

      executionData.forEach((exec) => {
        if (exec.status === "COMPLETED") {
          // Produce output beads
          for (let key in exec.output_data) {
            const outputEdges = newEdges.filter(
              (edge) =>
                edge.source === getFrontendId(exec.node_id, nodes) &&
                edge.sourceHandle === key,
            );
            outputEdges.forEach((edge) => {
              edge.data!.beadUp = (edge.data!.beadUp ?? 0) + 1;
              //todo kcze this assumes output at key is always array with one element
              edge.data!.beadData = [
                exec.output_data[key][0],
                ...edge.data!.beadData!,
              ];
            });
          }
        } else if (exec.status === "RUNNING") {
          // Consume input beads
          for (let key in exec.input_data) {
            const inputEdges = newEdges.filter(
              (edge) =>
                edge.target === getFrontendId(exec.node_id, nodes) &&
                edge.targetHandle === key,
            );

            inputEdges.forEach((edge) => {
              if (
                edge.data!.beadData![edge.data!.beadData!.length - 1] !==
                exec.input_data[key]
              ) {
                return;
              }
              edge.data!.beadDown = (edge.data!.beadDown ?? 0) + 1;
              edge.data!.beadData! = edge.data!.beadData!.slice(0, -1);
            });
          }
        }
      });

      return newEdges;
    });
  }

  const updateNodesWithExecutionData = (
    executionData: NodeExecutionResult[],
  ) => {
    console.log("Updating nodes with execution data:", executionData);
    setRootNodes((nodes) => {
      if (visualizeBeads !== "no") {
        updateEdgeBeads(executionData, nodes);
      }

      const updatedNodes = nodes.map((node) => {

        const nodeExecution = executionData.find(
          (exec) => {
            // console.log('exec.node_id', exec.node_id)
            // console.log('node.data.backend_id ', node.data.backend_id)
            return exec.node_id === node.data.backend_id
          }
        );

        if (!nodeExecution || node.data.status === nodeExecution.status) {
          return node;
        }
        console.log(">>> Updating node", node.id, nodeExecution);

        return {
          ...node,
          data: {
            ...node.data,
            status: nodeExecution.status,
            output_data: nodeExecution.output_data,
            isOutputOpen: true,
          },
        };
      });

      return updatedNodes;
    });
  };

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (isAnyModalOpen) return; // Prevent copy/paste if any modal is open

      if (event.ctrlKey || event.metaKey) {
        if (event.key === "c" || event.key === "C") {
          // Copy selected nodes
          const selectedNodes = nodes.filter((node) => node.selected);
          const selectedEdges = edges.filter((edge) => edge.selected);
          setCopiedNodes(selectedNodes);
          setCopiedEdges(selectedEdges);
        }
        if (event.key === "v" || event.key === "V") {
          // Paste copied nodes
          if (copiedNodes.length > 0) {
            const oldToNewNodeIDMap: Record<string, string> = {};
            const pastedNodes = copiedNodes.map((node, index) => {
              const newNodeId = (nodeId + index).toString();
              oldToNewNodeIDMap[node.id] = newNodeId;
              return {
                ...node,
                id: newNodeId,
                position: {
                  x: node.position.x + 20, // Offset pasted nodes
                  y: node.position.y + 20,
                },
                data: {
                  ...node.data,
                  status: undefined, // Reset status
                  output_data: undefined, // Clear output data
                  setHardcodedValues: (values: { [key: string]: any }) => {
                    setRootNodes((nds) =>
                      nds.map((n) =>
                        n.id === newNodeId
                          ? {
                            ...n,
                            data: { ...n.data, hardcodedValues: values },
                          }
                          : n,
                      ),
                    );
                  },
                },
              };
            });
            setRootNodes((existingNodes) =>
              // Deselect copied nodes
              existingNodes.map((node) => ({ ...node, selected: false })),
            );
            addNodes(pastedNodes);
            setNodeId((prevId) => prevId + copiedNodes.length);

            const pastedEdges = copiedEdges.map((edge) => {
              const newSourceId = oldToNewNodeIDMap[edge.source] ?? edge.source;
              const newTargetId = oldToNewNodeIDMap[edge.target] ?? edge.target;
              return {
                ...edge,
                id: `${newSourceId}_${edge.sourceHandle}_${newTargetId}_${edge.targetHandle}_${Date.now()}`,
                source: newSourceId,
                target: newTargetId,
              };
            });
            addEdges(pastedEdges);
          }
        }
      }
    },
    [
      addNodes,
      addEdges,
      // getNodes,
      // getEdges,
      setRootNodes,
      copiedNodes,
      copiedEdges,
      nodeId,
      isAnyModalOpen,
    ],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [handleKeyDown]);

  const onNodesDelete = useCallback(() => {
    clearNodesStatusAndOutput();
  }, [clearNodesStatusAndOutput]);

  const editorControls: Control[] = [
    {
      label: "Undo",
      icon: <IconUndo2 />,
      onClick: handleUndo,
    },
    {
      label: "Redo",
      icon: <IconRedo2 />,
      onClick: handleRedo,
    },
    {
      label: "Run",
      icon: <IconPlay />,
      onClick: runAgent,
    },
  ];

  return (
    <FlowContext.Provider value={{ visualizeBeads }}>
      <div className={className}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={{ custom: CustomNode }}
          edgeTypes={{ custom: CustomEdge }}
          connectionLineComponent={ConnectionLine}
          onConnect={onConnect}
          onNodesChange={onNodesChange}
          onNodesDelete={onNodesDelete}
          onEdgesChange={onEdgesChange}
          onNodeDragStop={onNodeDragEnd}
          onNodeDragStart={onNodeDragStart}
          deleteKeyCode={["Backspace", "Delete"]}
          minZoom={0.2}
          maxZoom={2}
        >
          <Controls />
          <Background />
          <ControlPanel className="absolute z-10" controls={editorControls}>
            <BlocksControl blocks={availableNodes} addBlock={addNode} />
            <SaveControl
              agentMeta={savedAgent}
              onSave={saveAgent}
              onDescriptionChange={setAgentDescription}
              onNameChange={setAgentName}
            />
          </ControlPanel>
        </ReactFlow>
      </div>
    </FlowContext.Provider>
  );
};

const WrappedFlowEditor: typeof FlowEditor = (props) => (
  <ReactFlowProvider>
    <FlowEditor {...props} />
  </ReactFlowProvider>
);

export default WrappedFlowEditor;

function formatEdgeID(conn: Link | Connection): string {
  if ("sink_id" in conn) {
    return `${conn.source_id}_${conn.source_name}_${conn.sink_id}_${conn.sink_name}`;
  } else {
    return `${conn.source}_${conn.sourceHandle}_${conn.target}_${conn.targetHandle}`;
  }
}
