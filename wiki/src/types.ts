export interface WikiPage {
  slug: string;
  title: string;
  content: string;
  html: string;
  lastUpdated?: string;
}

export interface WikiConfig {
  title: string;
  description: string;
  contentDir: string;
  outputDir: string;
  templatesDir: string;
}

export interface TemplateData {
  title: string;
  content: string;
  pages: WikiPage[];
  currentSlug?: string;
}
