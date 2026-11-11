export interface Draft {
  id: number;
  title: string;
  body: string;
  platform: string;
  status: 'Draft' | 'Approved' | 'Published';
  image_prompt?: string;
  source_url?: string;
  media_url?: string;
  tags?: string;
  scheduled_for?: string;
  auto_publish?: number;
  created_at?: string;
  updated_at?: string;
  live_url?: string;
}

export interface SourceItem {
  title: string;
  url: string;
  snippet: string;
}

export interface DashboardStats {
  total: number;
  active: number;
  published: number;
  scheduled: number;
  rejected: number;
  recent_7days: number;
  platform_breakdown: Record<string, number>;
  tag_counts: Record<string, number>;
}

export interface ActivityItem {
  action: string;
  entity_type: string;
  entity_id: number;
  details: string;
  created_at: string;
}

export interface Template {
  id: number;
  name: string;
  platform: string;
  title_template: string;
  body_template: string;
  image_prompt_template: string;
  tags: string;
}

export interface ImageResult {
  ok: boolean;
  filename?: string;
  b64?: string;
  image_url?: string;
  error?: string;
}

export interface GithubRepo {
  full_name: string;
  url: string;
  description: string;
  stars: number;
  language: string;
}
