/** Хуки доступа к данным сервера. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, request } from "./client";
import type {
  CheckpointsResponse,
  ReportView,
  SearchResponse,
  DashboardResponse,
  EventDetailResponse,
  EventsResponse,
  NotificationsResponse,
  QueuesResponse,
  SourceSummaryResponse,
} from "./types";

import type {
  FramePreview,
  HealthResponse,
  Markup,
  SettingsResponse,
  Source,
  SourcesResponse,
  User,
  Video,
} from "./types";

export const keys = {
  health: ["health"] as const,
  me: ["me"] as const,
  sources: ["sources"] as const,
  source: (id: number) => ["source", id] as const,
  geometry: (id: number) => ["geometry", id] as const,
  videos: ["videos"] as const,
  settings: ["settings"] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => request<HealthResponse>("/api/health"),
    staleTime: 60_000,
  });
}

export function useMe(enabled = true) {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => request<{ user: User }>("/api/auth/me", { allowUnauthorized: true }),
    enabled,
    retry: false,
    select: (data) => data.user,
  });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { login: string; password: string }) =>
      request<{ user: User }>("/api/auth/login", {
        method: "POST",
        body: credentials,
        allowUnauthorized: true,
      }),
    onSuccess: (data) => client.setQueryData(keys.me, data),
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => client.clear(),
  });
}

export function useUpdateProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Pick<User, "displayName" | "profile" | "dataset" | "liveUpdates">>) =>
      request<{ user: User; demoReady: boolean | null }>("/api/auth/me", {
        method: "PATCH",
        body: {
          display_name: payload.displayName,
          profile: payload.profile,
          dataset: payload.dataset,
          live_updates: payload.liveUpdates,
        },
      }),
    onSuccess: (data) => client.setQueryData(keys.me, data),
  });
}

/** Список источников обновляется сам: состояние источников меняется без нас. */
export function useSources(enabled = true) {
  return useQuery({
    queryKey: keys.sources,
    queryFn: () => request<SourcesResponse>("/api/sources"),
    enabled,
    refetchInterval: enabled ? 10_000 : false,
  });
}

export function useSource(id: number | null) {
  return useQuery({
    queryKey: keys.source(id ?? 0),
    queryFn: () => request<{ source: Source }>(`/api/sources/${id}`),
    enabled: id !== null,
    select: (data) => data.source,
  });
}

export function useGeometry(id: number | null) {
  return useQuery({
    queryKey: keys.geometry(id ?? 0),
    queryFn: () => request<{ markup: Markup }>(`/api/sources/${id}/geometry`),
    enabled: id !== null,
    select: (data) => data.markup,
  });
}

export function useVideos() {
  return useQuery({
    queryKey: keys.videos,
    queryFn: () => request<{ videos: Video[] }>("/api/videos"),
    select: (data) => data.videos,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => request<SettingsResponse>("/api/settings"),
  });
}

function invalidateSources(client: ReturnType<typeof useQueryClient>, id?: number) {
  client.invalidateQueries({ queryKey: keys.sources });
  if (id !== undefined) {
    client.invalidateQueries({ queryKey: keys.source(id) });
    client.invalidateQueries({ queryKey: keys.geometry(id) });
  }
}

export function useCreateSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      request<{ source: Source; nextStep: string }>("/api/sources", { method: "POST", body: payload }),
    onSuccess: () => invalidateSources(client),
  });
}

export function useUpdateSource(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      request<{ source: Source; warning: string | null }>(`/api/sources/${id}`, {
        method: "PATCH",
        body: payload,
      }),
    onSuccess: () => invalidateSources(client, id),
  });
}

export function useDeleteSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      request<{ ok: boolean; message: string }>(`/api/sources/${id}`, { method: "DELETE" }),
    onSuccess: () => invalidateSources(client),
  });
}

export function useSourceAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: "enable" | "disable" | "check" | "restart" | "restart-playback" }) =>
      request<Record<string, unknown>>(`/api/sources/${id}/${action}`, { method: "POST" }),
    onSuccess: (_data, variables) => invalidateSources(client, variables.id),
  });
}

export function useSaveGeometry(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (markup: Markup) =>
      request<{ markup: Markup; source: Source; message: string }>(`/api/sources/${id}/geometry`, {
        method: "PUT",
        body: markup,
      }),
    onSuccess: () => invalidateSources(client, id),
  });
}

/** Кадр для разметки: тяжёлый запрос, поэтому дёргается только по требованию. */
export function fetchFrame(id: number, position: number, detect = true): Promise<FramePreview> {
  const params = new URLSearchParams({ pos: String(position), detect: String(detect) });
  return request<FramePreview>(`/api/sources/${id}/frame?${params.toString()}`);
}

export function useSaveSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      request<SettingsResponse>("/api/settings", { method: "PUT", body: payload }),
    onSuccess: (data) => {
      client.setQueryData(keys.settings, data);
      client.invalidateQueries({ queryKey: keys.sources });
    },
  });
}

export function useResetSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<SettingsResponse>("/api/settings/reset", { method: "POST" }),
    onSuccess: (data) => client.setQueryData(keys.settings, data),
  });
}

// --- аналитика и события ----------------------------------------------------


export interface AnalyticsQuery {
  period: string;
  scope: string;
  from?: string | null;
  to?: string | null;
}

function analyticsParams(query: AnalyticsQuery): string {
  const params = new URLSearchParams({ period: query.period, scope: query.scope });
  if (query.period === "custom" && query.from && query.to) {
    params.set("from", query.from);
    params.set("to", query.to);
  }
  return params.toString();
}

export function useDashboard(query: AnalyticsQuery, dataset: string) {
  return useQuery({
    queryKey: ["dashboard", query, dataset],
    queryFn: () => request<DashboardResponse>(`/api/dashboard?${analyticsParams(query)}`),
    refetchInterval: 30_000,
  });
}

export function useQueuesAnalytics(query: AnalyticsQuery, dataset: string) {
  return useQuery({
    queryKey: ["queues", query, dataset],
    queryFn: () => request<QueuesResponse>(`/api/analytics/queues?${analyticsParams(query)}`),
    refetchInterval: 60_000,
  });
}

export function useCheckpointsAnalytics(query: AnalyticsQuery, dataset: string) {
  return useQuery({
    queryKey: ["checkpoints", query, dataset],
    queryFn: () => request<CheckpointsResponse>(`/api/analytics/checkpoints?${analyticsParams(query)}`),
    refetchInterval: 60_000,
  });
}

export function useSourceSummary(sourceId: number | null, query: AnalyticsQuery, dataset: string) {
  return useQuery({
    queryKey: ["source-summary", sourceId, query, dataset],
    queryFn: () =>
      request<SourceSummaryResponse>(`/api/sources/${sourceId}/summary?${analyticsParams(query)}`),
    enabled: sourceId !== null,
  });
}

export interface EventsQuery extends AnalyticsQuery {
  severity?: string;
  status?: string;
  state?: string;
  type?: string;
  sourceId?: number | null;
  q?: string;
  sort?: string;
  order?: string;
  page?: number;
  pageSize?: number;
}

export function eventsParams(query: EventsQuery): string {
  const params = new URLSearchParams({ period: query.period, scope: query.scope });
  if (query.period === "custom" && query.from && query.to) {
    params.set("from", query.from);
    params.set("to", query.to);
  }
  const optional: Array<[string, unknown]> = [
    ["severity", query.severity],
    ["status", query.status],
    ["state", query.state],
    ["type", query.type],
    ["sourceId", query.sourceId],
    ["q", query.q],
    ["sort", query.sort],
    ["order", query.order],
    ["page", query.page],
    ["pageSize", query.pageSize],
  ];
  for (const [key, value] of optional) {
    if (value !== undefined && value !== null && value !== "" && value !== "all") {
      params.set(key, String(value));
    }
  }
  return params.toString();
}

export function useEvents(query: EventsQuery, dataset: string) {
  return useQuery({
    queryKey: ["events", query, dataset],
    queryFn: () => request<EventsResponse>(`/api/events?${eventsParams(query)}`),
    refetchInterval: 30_000,
  });
}

export function useEvent(eventId: number | null) {
  return useQuery({
    queryKey: ["event", eventId],
    queryFn: () => request<EventDetailResponse>(`/api/events/${eventId}`),
    enabled: eventId !== null,
  });
}

export function useChangeEventStatus() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      id: number;
      status: string;
      comment?: string;
      expectedStatus?: string;
    }) =>
      request<{ event: EventDetailResponse["event"] }>(`/api/events/${payload.id}/status`, {
        method: "POST",
        body: {
          status: payload.status,
          comment: payload.comment ?? "",
          expected_status: payload.expectedStatus,
        },
      }),
    onSuccess: (_data, variables) => {
      client.invalidateQueries({ queryKey: ["events"] });
      client.invalidateQueries({ queryKey: ["event", variables.id] });
      client.invalidateQueries({ queryKey: ["notifications"] });
      client.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useBulkEventStatus() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: { ids: number[]; status: string; comment?: string }) =>
      request<{ updated: number; message: string }>("/api/events/bulk-status", {
        method: "POST",
        body: { ids: payload.ids, status: payload.status, comment: payload.comment ?? "" },
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["events"] });
      client.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useNotifications(enabled = true) {
  return useQuery({
    queryKey: ["notifications"],
    queryFn: () => request<NotificationsResponse>("/api/notifications"),
    enabled,
    refetchInterval: 30_000,
  });
}

export function useMarkNotificationsSeen() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<{ seenAt: string }>("/api/notifications/seen", { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

export function useDemoStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["demo-status"],
    queryFn: () => request<{ ready: boolean; running: boolean; error: string | null }>("/api/demo/status"),
    enabled,
    refetchInterval: (query) => (query.state.data?.running ? 2_000 : false),
  });
}

// --- отчёты и поиск ---------------------------------------------------------

export interface ReportParams {
  scope: "canteen" | "gate" | "source";
  source_id?: number | null;
  period: string;
  date_from?: string | null;
  date_to?: string | null;
  step?: string | null;
}

export function useReportPreview() {
  return useMutation({
    mutationFn: (params: ReportParams) =>
      request<{ report: ReportView }>("/api/reports/preview", { method: "POST", body: params }),
  });
}

/** Выгрузка идёт тем же запросом, что и предпросмотр, — файл не разойдётся с экраном. */
export async function downloadReport(
  params: ReportParams & { format: "csv" | "xlsx" | "pdf" },
): Promise<string> {
  const response = await fetch("/api/reports/export", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });

  if (!response.ok) {
    let message = "Не удалось сформировать файл.";
    try {
      const body = await response.json();
      message = body?.error?.message ?? message;
    } catch {
      // Тело не разобралось — оставим общее сообщение.
    }
    throw new ApiError("export_failed", message, response.status);
  }

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const name = match ? match[1] : `uniflow-report.${params.format}`;

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
  return name;
}

export function useSearch(query: string) {
  return useQuery({
    queryKey: ["search", query],
    queryFn: () => request<SearchResponse>(`/api/search?q=${encodeURIComponent(query)}`),
    enabled: query.trim().length >= 2,
    staleTime: 10_000,
  });
}
