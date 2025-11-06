import { marked } from 'marked';
import type { WikiPage } from './types';

/**
 * Parse markdown content and extract metadata
 */
export async function parseMarkdown(content: string, slug: string): Promise<WikiPage> {
  // Extract title from first H1 heading
  const titleMatch = content.match(/^#\s+(.+)$/m);
  const title = titleMatch ? titleMatch[1] : slug;
  
  // Convert markdown to HTML
  const html = await marked(content);
  
  // Extract last updated date if present
  const dateMatch = content.match(/\*Last updated:\s*(.+?)\*/);
  const lastUpdated = dateMatch ? dateMatch[1] : undefined;
  
  return {
    slug,
    title,
    content,
    html,
    lastUpdated,
  };
}

/**
 * Convert markdown links to proper HTML links
 */
export function processLinks(html: string): string {
  // Convert wiki-style links [text](slug) to proper URLs
  return html.replace(
    /href="([^"]+)"/g,
    (match, slug) => {
      // If it's already a full URL, leave it
      if (slug.startsWith('http://') || slug.startsWith('https://') || slug.startsWith('/')) {
        return match;
      }
      // Otherwise, make it a relative link to a wiki page
      return `href="/${slug}.html"`;
    }
  );
}
