export interface NodeResponse {
  id: string;
  cpu_cores: number;
  memory_mib: number;
  vram_mib: number;
  available_cpu_cores: number;
  available_memory_mib: number;
  available_vram_mib: number;
  is_alive: boolean;
}

export interface ListNodesResponse {
  nodes: NodeResponse[];
}

export type JobStatus =
  | "SUBMITTED"
  | "QUEUED"
  | "SCHEDULED"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface JobSummaryResponse {
  id: string;
  status: JobStatus;
  cpu_cores: number;
  memory_mib: number;
  vram_mib: number;
  exit_code: number | null;
  submitted_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ListJobsResponse {
  jobs: JobSummaryResponse[];
}

export interface ClusterHealthResponse {
  total_nodes: number;
  alive_nodes: number;
  offline_nodes: number;
}

export interface ClusterCapacityResponse {
  cpu_cores: number;
  memory_mib: number;
  vram_mib: number;
}

export interface ClusterUtilizationResponse {
  cpu_cores: number;
  memory_mib: number;
  vram_mib: number;
}

export interface EventResponse {
  id: string;
  aggregate_id: string;
  aggregate_type: string;
  event_type: string;
  occurred_at: string;
  payload: Record<string, string>;
}

export interface ListEventsResponse {
  events: EventResponse[];
}
