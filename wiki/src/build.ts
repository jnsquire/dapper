import { readdir, readFile, writeFile, mkdir } from 'fs/promises';
import { join, basename } from 'path';
import { parseMarkdown, processLinks } from './markdown';
import { renderPage, generateStyles } from './template';
import type { WikiPage, WikiConfig } from './types';

const config: WikiConfig = {
  title: 'Things the Humans Should Know',
  description: 'A collaborative knowledge base for essential human knowledge',
  contentDir: join(import.meta.dir, '../content/articles'),
  outputDir: join(import.meta.dir, '../dist'),
  templatesDir: join(import.meta.dir, '../templates'),
};

/**
 * Load all markdown files from the content directory
 */
async function loadArticles(): Promise<WikiPage[]> {
  const files = await readdir(config.contentDir);
  const markdownFiles = files.filter(f => f.endsWith('.md'));
  
  const pages: WikiPage[] = [];
  
  for (const file of markdownFiles) {
    const filePath = join(config.contentDir, file);
    const content = await readFile(filePath, 'utf-8');
    const slug = basename(file, '.md');
    const page = await parseMarkdown(content, slug);
    pages.push(page);
  }
  
  // Sort pages: home first, then alphabetically
  pages.sort((a, b) => {
    if (a.slug === 'home') return -1;
    if (b.slug === 'home') return 1;
    return a.title.localeCompare(b.title);
  });
  
  return pages;
}

/**
 * Build the static site
 */
export async function build(): Promise<void> {
  console.log('🚀 Building wiki...');
  
  // Create output directory
  await mkdir(config.outputDir, { recursive: true });
  
  // Load all articles
  const pages = await loadArticles();
  console.log(`📄 Loaded ${pages.length} articles`);
  
  // Generate HTML for each page
  for (const page of pages) {
    const processedHtml = processLinks(page.html);
    const html = renderPage({
      title: page.title,
      content: processedHtml,
      pages,
      currentSlug: page.slug,
    });
    
    const outputPath = join(config.outputDir, `${page.slug}.html`);
    await writeFile(outputPath, html, 'utf-8');
    console.log(`  ✅ Generated ${page.slug}.html`);
  }
  
  // Generate CSS
  const css = generateStyles();
  await writeFile(join(config.outputDir, 'styles.css'), css, 'utf-8');
  console.log('  ✅ Generated styles.css');
  
  // Create index.html as redirect to home
  const indexHtml = `<!DOCTYPE html>
<html>
<head>
  <meta http-equiv="refresh" content="0; url=/home.html">
  <title>Redirecting...</title>
</head>
<body>
  <p>Redirecting to <a href="/home.html">home page</a>...</p>
</body>
</html>`;
  await writeFile(join(config.outputDir, 'index.html'), indexHtml, 'utf-8');
  console.log('  ✅ Generated index.html');
  
  console.log('✨ Build complete!');
}

/**
 * Watch for changes and rebuild
 */
export async function watch(): Promise<void> {
  console.log('👀 Watching for changes...');
  
  const watcher = Bun.file(config.contentDir);
  
  // Initial build
  await build();
  
  // Watch for file changes
  const fs = await import('fs');
  fs.watch(config.contentDir, { recursive: true }, async (eventType, filename) => {
    if (filename && filename.endsWith('.md')) {
      console.log(`\n📝 Change detected: ${filename}`);
      try {
        await build();
      } catch (error) {
        console.error('❌ Build failed:', error);
      }
    }
  });
}

// Run build if this is the main module
if (import.meta.main) {
  build().catch(error => {
    console.error('❌ Build failed:', error);
    process.exit(1);
  });
}
