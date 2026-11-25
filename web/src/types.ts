// The shapes the API sends and accepts. The study format itself comes from
// generated/schema.json (packtherm.study.schema()); the results shape is
// checked against the committed example results in contract.test.ts.

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

/** One key of the study format, as packtherm.study.schema() describes it. */
export interface KeyRule {
  type: string[];
  default: Json;
  choices?: (string | number)[];
  min?: number;
  max?: number;
  exclusive?: boolean;
  items?: KeyRule;
}

export interface Schema {
  packtherm_study: number;
  required: string[];
  top: Record<string, KeyRule>;
  duty: { keys: Record<string, KeyRule>; uses: Record<string, string[]> };
  requirements: Record<string, KeyRule>;
  design_space: Record<string, KeyRule>;
  options: Record<string, KeyRule>;
  cell: {
    keys: Record<string, KeyRule>;
    required: string[];
    formats_mm: Record<string, { diameter: number; height: number }>;
  };
}

export type Section = "requirements" | "design_space" | "options";

/** A study document (the study-file format). Values the form leaves out take their defaults. */
export interface Study {
  packtherm_study: 1;
  name?: string;
  cell: string | Record<string, Json>;
  mode?: "normal" | "fast";
  ambient_C?: number;
  duty: Record<string, Json>;
  requirements?: Record<string, Json>;
  design_space?: Record<string, Json>;
  options?: Record<string, Json>;
}

export interface Limits {
  max_designs_fast: number;
  max_designs_normal: number;
  max_simulated_h: number;
  max_steps: number;
  max_runtime_s: number;
  max_running: number;
  max_queued: number;
  rate_per_hour: number;
  max_request_kB: number;
  keep_h: number;
}

export interface LibraryCell {
  name: string;
  group?: string; // v0.6.9: "comparison" models are listed apart from the cells to design with
  model: string;
  format: string;
  capacity_Ah: number;
  V_nominal: number;
  DCIR_25C_mOhm: number;
  mass_g: number;
}

export interface CellCheck {
  cell: Record<string, Json>;
  derived: Record<string, Json>;
  warnings: string[];
}

export interface StudyCheck {
  designs: number;
  mode: "normal" | "fast";
  within_limits: boolean;
  problems: string[];
}

export type JobState = "queued" | "running" | "done" | "failed" | "cancelled";

export interface JobStatus {
  id: string;
  state: JobState;
  created: number;
  started: number | null;
  finished: number | null;
  error: string | null;
  progress: { stage: string; done: number; total: number } | null;
  eta_s?: number;
  queue_position?: number;
  files: Record<string, string> | null;
}

export interface Submitted {
  id: string;
  state: JobState;
  designs: number;
  mode: "normal" | "fast";
}

/** One evaluated design (a row of the designs table). */
export interface Design {
  design: string;
  cooling: string;
  topology: string;
  cooling_kind: string;
  chilled: boolean;
  filler: string;
  pcm: string;
  gap_mm: number | null;
  T_peak_C: number | null;
  dT_cell_C: number | null;
  cell_to_cell_K: number | null;
  recovery_min: number | null;
  aux_energy_pct: number | null;
  capacity_after_pct?: number | null;
  life_years?: number | null;
  life_model?: string | null;
  mass_overhead_pct: number | null;
  mass_overhead_g: number | null;
  T_limit_C: number | null;
  T_margin_C: number | null;
  feasible: boolean;
  fail_reason: string;
  rating_warning: string;
  pareto: boolean;
  robust: boolean | null;
  [key: string]: Json | undefined;
}

export interface Pick extends Design {
  pick: string;
}

export interface Results {
  packtherm_results: number;
  packtherm_version: string;
  created: string;
  elapsed_s: number;
  study: Record<string, Json>;
  summary: {
    cell: string;
    cell_model?: string;
    duty: string;
    mode: string;
    designs: number;
    feasible: number;
    on_front: number;
    T_limit_C: number | null;
    text: string;
  };
  /** Chart and table labels (from 0.5.5; older results files lack them). */
  labels?: { mass_axis: string; energy_axis: string; filler: string; kinds: Record<string, string> };
  picks: Pick[];
  notes: string[];
  assumptions: Record<string, Json>;
  designs: Design[];
}
