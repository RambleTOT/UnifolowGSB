/** Типы ответов сервера. Имена полей совпадают с тем, что отдаёт API. */

export type SourceStatus = "online" | "degraded" | "offline" | "disabled" | "no_video";
export type ModelStatus = "ready" | "warming_up" | "error" | "unavailable";
export type AnalysisMode = "realtime" | "precomputed" | "auto";
export type Scope = "canteen" | "gate";
export type ReadinessState = "no_video" | "file_missing" | "no_markup" | "partial" | "ready";

export interface User {
  id: number;
  login: string;
  displayName: string;
  profile: "ops" | "security" | "manager" | "admin";
  profileTitle: string;
  start: { section: string; scope: string };
  dataset: "real" | "demo";
  liveUpdates: boolean;
  notificationsSeenAt: string | null;
}

export interface Video {
  id: number;
  name: string;
  durationSeconds: number;
  width: number;
  height: number;
  fps: number;
  sizeBytes: number;
  resolution: string | null;
  uploadedAt: string;
}

export interface Point {
  0: number;
  1: number;
  length: 2;
}

export interface MarkupLine {
  id: string;
  name: string;
  a: [number, number];
  b: [number, number];
  entry_side: number;
  counts: "in" | "out" | "both";
}

export interface MarkupZone {
  id: string;
  name: string;
  kind: "queue" | "occupancy";
  min_dwell_seconds: number;
  capacity: number | null;
  polygon: Array<[number, number]>;
}

export interface Markup {
  anchor: "bottom_center" | "center";
  lines: MarkupLine[];
  zones: MarkupZone[];
}

export interface LiveObject {
  trackId: number;
  bbox: [number, number, number, number];
  confidence: number;
  state: "moving" | "queue" | "crossing";
  anchor: [number, number];
}

export interface LiveCrossing {
  lineId: string;
  lineName: string;
  direction: "in" | "out";
  trackId: number;
  point: [number, number];
}

export interface LiveZone {
  id: string;
  name: string;
  kind: "queue" | "occupancy";
  polygon: Array<[number, number]>;
  people: number;
  capacity: number | null;
}

export interface LiveLine {
  id: string;
  name: string;
  a: [number, number];
  b: [number, number];
  entrySide: number;
  counts: "in" | "out" | "both";
  entered: number;
  exited: number;
}

export interface LiveMessage {
  sourceId: number;
  name: string;
  status: SourceStatus;
  modelStatus: ModelStatus;
  warmupPercent: number | null;
  analysisMode: AnalysisMode;
  error: string | null;
  isStream: boolean;
  resolution: string | null;
  frameIndex: number;
  positionSeconds: number;
  durationSeconds: number;
  loop: {
    number: number;
    entered: number;
    exited: number;
    previousEntered: number | null;
    previousExited: number | null;
  };
  metrics: {
    peopleInFrame: number;
    peopleInZone: number;
    queue: number;
    entriesToday: number;
    exitsToday: number;
    insideNow: number;
    avgWaitSeconds: number | null;
  };
  technical: { fps: number; latencyMs: number; confidence: number | null };
  objects: LiveObject[];
  crossings: LiveCrossing[];
  zones: LiveZone[];
  lines: LiveLine[];
  updatedAt: string | null;
}

export type ConnectionType = "video_loop" | "stream";
export type ModelProfile = "fast" | "standard" | "accurate" | "far";

export interface Source {
  id: number;
  name: string;
  scope: Scope;
  location: string;
  tags: string[];
  enabled: boolean;
  deleted: boolean;
  connectionType: ConnectionType;
  streamUrl: string | null;
  video: Video | null;
  videoAvailable: boolean;
  modelProfile: ModelProfile;
  modelProfileOverride: boolean;
  confidence: number | null;
  aggregationSeconds: number | null;
  readiness: { state: ReadinessState; missing: string[] };
  primaryMetric: "flow" | "queue" | "occupancy" | "none";
  status: SourceStatus;
  lastSignalAt: string | null;
  lastError: string | null;
  live: LiveMessage | null;
  markup?: Markup;
}

export interface DataStatus {
  state: "ok" | "partial" | "no_data" | "no_sources";
  healthy: number;
  countable: number;
  total: number;
  problems: Array<{
    sourceId: number;
    name: string;
    status: SourceStatus;
    error: string | null;
  }>;
}

export interface SourcesResponse {
  sources: Source[];
  dataStatus: DataStatus;
}

export interface SystemPulse {
  type: "pulse";
  at: string;
  dataStatus: DataStatus;
  sources: Array<{
    sourceId: number;
    name: string;
    status: SourceStatus;
    modelStatus: ModelStatus;
    warmupPercent: number | null;
    analysisMode: AnalysisMode;
    error: string | null;
    queue: number;
    peopleInFrame: number;
    entriesToday: number;
    exitsToday: number;
    insideNow: number;
  }>;
}

export interface SystemSettings {
  model_profile: ModelProfile;
  tracker: string;
  confidence: number;
  queue_threshold: number;
  wait_threshold_minutes: number;
  checkpoint_threshold_per_minute: number;
  event_min_duration_seconds: number;
  retention_days: number;
  aggregation_seconds: number;
  save_event_snapshots: boolean;
}

export interface SettingsResponse {
  values: SystemSettings;
  bounds: Record<string, [number, number]>;
  message?: string;
  restarted?: boolean;
}

export interface FramePreview {
  image: string;
  positionSeconds: number;
  durationSeconds: number;
  width: number;
  height: number;
  anchors: Array<[number, number]>;
}

export interface HealthResponse {
  status: string;
  time: string;
  timezone: string;
  device: string;
  deviceTitle: string;
  analysisMode: AnalysisMode;
  upload: { maxSizeMb: number; formats: string[] };
}

export interface MetricView {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  deltaPercent: number | null;
  direction: "up" | "down" | "flat";
  meaning: "better" | "worse" | "neutral";
  level: "normal" | "good" | "attention" | "critical";
  hint: string | null;
  missingReason: string | null;
  incomplete: { counted: number; total: number; names: string[] } | null;
}

export interface SeriesPoint {
  at: string;
  samples: number;
  [key: string]: number | string | null;
}

export interface WindowView {
  period: string;
  from: string;
  to: string;
  previousFrom: string;
  previousTo: string;
  stepSeconds: number;
  stepTitle: string;
}

export interface EventView {
  id: number;
  type: string;
  severity: "low" | "medium" | "high" | "critical";
  title: string;
  description: string;
  sourceId: number;
  sourceName: string;
  sourceDeleted: boolean;
  scope: string | null;
  startedAt: string;
  endedAt: string | null;
  durationSeconds: number | null;
  ongoing: boolean;
  status: "open" | "investigating" | "resolved";
  metricValue: number;
  peakValue: number;
  threshold: number;
  exceedPercent: number | null;
  snapshotAvailable: boolean;
  videoPositionSeconds: number | null;
  loopNumber: number | null;
  dataset: string;
  history?: Array<{
    at: string;
    author: string;
    fromStatus: string;
    toStatus: string;
    comment: string;
  }>;
}

export interface HeatmapView {
  cells: Array<{ weekday: number; hour: number; flow: number; queue: number }>;
  daysCollected: number;
  daysRequired: number;
}

export interface DashboardResponse {
  window: WindowView;
  dataset: string;
  attention: {
    events: EventView[];
    sources: Array<{
      sourceId: number;
      name: string;
      status: SourceStatus;
      readiness: { state: ReadinessState; missing: string[] };
      error: string | null;
    }>;
  };
  metrics: MetricView[];
  flowSeries: SeriesPoint[];
  queueSeries: SeriesPoint[];
  thresholds: { queue: number; waitMinutes: number; checkpointPerMinute: number };
  sourceLoad: Array<{
    sourceId: number;
    name: string;
    scope: string | null;
    flow: number;
    queueAvg: number;
    peopleAvg: number;
  }>;
  distribution: Array<{ sourceId: number; name: string; flow: number; share: number }>;
  heatmap: HeatmapView;
  hourlyProfile: { points: Array<{ hour: number; flow: number | null }>; daysCollected: number; daysRequired: number };
  sourcesTotal: number;
}

export interface QueuesResponse {
  window: WindowView;
  dataset: string;
  applicable: boolean;
  notApplicableReason: string | null;
  metrics: MetricView[];
  queueSeries: SeriesPoint[];
  zones: Array<{
    sourceId: number;
    sourceName: string;
    zoneId: string;
    name: string;
    queueAvg: number;
    queueMax: number;
    waitAvgMinutes: number | null;
  }>;
  heatmap: HeatmapView;
  events: EventView[];
  thresholds: { queue: number; waitMinutes: number };
}

export interface CheckpointsResponse {
  window: WindowView;
  dataset: string;
  applicable: boolean;
  notApplicableReason: string | null;
  singleCheckpoint: boolean;
  metrics: MetricView[];
  flowSeries: SeriesPoint[];
  direction: { entered: number; exited: number; enteredShare: number };
  lines: Array<{
    sourceId: number;
    sourceName: string;
    lineId: string;
    name: string;
    entered: number;
    exited: number;
    total: number;
    share: number;
  }>;
  weekdays: Array<{ weekday: number; title: string; current: number | null; baseline: number | null }>;
  events: EventView[];
  thresholds: { checkpointPerMinute: number };
}

export interface EventsResponse {
  events: EventView[];
  total: number;
  page: number;
  pageSize: number;
  window: WindowView;
  attentionCount: number;
  dataset: string;
}

export interface EventDetailResponse {
  event: EventView;
  series: SeriesPoint[];
  seriesWindow: WindowView;
  nearby: EventView[];
}

export interface NotificationsResponse {
  unseen: number;
  events: EventView[];
  critical: EventView[];
  seenAt: string | null;
}

export interface SourceSummaryResponse {
  window: WindowView;
  dataset: string;
  metrics: MetricView[];
  flowSeries: SeriesPoint[];
  zones: QueuesResponse["zones"];
  lines: CheckpointsResponse["lines"];
}

export interface ReportColumn {
  key: string;
  title: string;
  unit: string;
}

export interface ReportView {
  title: string;
  parameters: {
    scope: "canteen" | "gate" | "source";
    sourceId: number | null;
    sourceName: string | null;
    period: string;
    from: string;
    to: string;
    step: string;
    stepTitle: string;
  };
  generatedAt: string;
  author: string;
  dataset: string;
  demo: boolean;
  stepHint: string | null;
  sources: Array<{ id: number; name: string }>;
  summary: MetricView[];
  columns: ReportColumn[];
  rows: Array<Record<string, number | string | null>>;
  events: EventView[];
  totals: { rows: number; entered: number; exited: number };
}

export interface SearchResponse {
  query: string;
  sections: Array<{ title: string; to: string }>;
  sources: Array<{
    id: number;
    name: string;
    location: string;
    scope: string;
    status: string;
    to: string;
    reportTo: string;
    readiness: string;
  }>;
  events: Array<EventView & { to: string }>;
  total: number;
}
