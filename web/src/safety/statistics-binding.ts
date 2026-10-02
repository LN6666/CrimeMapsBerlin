/** Bind saved count-only statistics to the currently loaded single-city map. */
export interface StatisticsBinding {
  schema_version: 1;
  city: string;
  map_generation: string;
  map_announcements: number;
  mapping_sha256: string;
  static_reports_checked: boolean;
}
export function statisticsBinding(value: unknown, city: string, generation: string, announcements: number): StatisticsBinding {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw Error("Missing statistics binding");
  const binding = value as StatisticsBinding;
  if (binding.schema_version !== 1 || binding.city !== city || binding.map_generation !== generation ||
      !/^[a-f0-9]{16}-\d{8}T\d{6}$/.test(binding.map_generation) ||
      !Number.isSafeInteger(binding.map_announcements) || binding.map_announcements < 0 ||
      binding.map_announcements !== announcements || !/^[a-f0-9]{64}$/.test(binding.mapping_sha256) ||
      typeof binding.static_reports_checked !== "boolean") throw Error("Statistics belong to a different map snapshot");
  return binding;
}
