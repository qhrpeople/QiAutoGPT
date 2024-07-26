import { FC, memo, useMemo } from "react";
import { BaseEdge, EdgeLabelRenderer, EdgeProps, getBezierPath, useReactFlow, XYPosition } from "reactflow";
import './customedge.css';
import { X } from 'lucide-react';

export type CustomEdgeData = {
  edgeColor: string
  sourcePos: XYPosition
}

const CustomEdgeFC: FC<EdgeProps<CustomEdgeData>> = ({ id, data, selected, source, sourcePosition, sourceX, sourceY, target, targetPosition, targetX, targetY, markerEnd }) => {

  const { setEdges } = useReactFlow();

  const onEdgeClick = () => {
    setEdges((edges) => edges.filter((edge) => edge.id !== id));
  }

  const [path, labelX, labelY] = getBezierPath({
    sourceX: sourceX - 5,
    sourceY,
    sourcePosition,
    targetX: targetX + 4,
    targetY,
    targetPosition,
  });

  // Calculate y difference between source and source node, to adjust self-loop edge
  const yDifference = useMemo(() => sourceY - data!.sourcePos.y, [data!.sourcePos.y]);

  // Define special edge path for self-loop
  const edgePath = source === target ?
    `M ${sourceX - 5} ${sourceY} C ${sourceX + 128} ${sourceY - yDifference - 128} ${targetX - 128} ${sourceY - yDifference - 128} ${targetX + 3}, ${targetY}` :
    path;

  console.table({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, path, labelX, labelY });

  return (
    <>
      <BaseEdge
        style={{ strokeWidth: 2, stroke: (data?.edgeColor ?? '#555555') + (selected ? '' : '80') }}
        path={edgePath}
        markerEnd={markerEnd}
      />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="edge-label-renderer"
        >
          <button className="edge-label-button" onClick={onEdgeClick}>
            <X size={14} />
          </button>
        </div>
      </EdgeLabelRenderer>    
    </>
  )
};

export const CustomEdge = memo(CustomEdgeFC);
