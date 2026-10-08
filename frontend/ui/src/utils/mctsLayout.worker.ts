import { buildSearchGraph, type GraphInputNode } from './mctsGraph'

const worker = self as unknown as {
  onmessage: ((event: MessageEvent<{ revision: number; nodes: GraphInputNode[] }>) => void) | null
  postMessage: (message: unknown) => void
}

worker.onmessage = ({ data }) => {
  try { worker.postMessage({ revision: data.revision, graph: buildSearchGraph(data.nodes) }) }
  catch (error) { worker.postMessage({ revision: data.revision, error: error instanceof Error ? error.message : String(error) }) }
}
