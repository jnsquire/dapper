import type { TemplateData } from './types';

/**
 * Generate the main HTML template for wiki pages
 */
export function renderPage(data: TemplateData): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${data.title} - Things the Humans Should Know</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <div class="wiki-container">
    <aside class="wiki-sidebar">
      <div class="wiki-logo">
        <h1><a href="/home.html">Things the Humans<br>Should Know</a></h1>
      </div>
      <nav class="wiki-nav">
        <h2>Articles</h2>
        <ul>
          ${data.pages.map(page => `
            <li class="${page.slug === data.currentSlug ? 'active' : ''}">
              <a href="/${page.slug}.html">${page.title}</a>
            </li>
          `).join('')}
        </ul>
      </nav>
      <div class="wiki-footer">
        <p>A collaborative knowledge base</p>
      </div>
    </aside>
    <main class="wiki-content">
      <article>
        ${data.content}
      </article>
    </main>
  </div>
</body>
</html>`;
}

/**
 * Generate CSS styles for the wiki
 */
export function generateStyles(): string {
  return `/* Reset and base styles */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  line-height: 1.6;
  color: #202122;
  background-color: #f8f9fa;
}

/* Wiki container layout */
.wiki-container {
  display: flex;
  min-height: 100vh;
}

/* Sidebar */
.wiki-sidebar {
  width: 280px;
  background-color: #fff;
  border-right: 1px solid #a2a9b1;
  padding: 20px;
  position: fixed;
  height: 100vh;
  overflow-y: auto;
  left: 0;
  top: 0;
}

.wiki-logo h1 {
  font-size: 1.3rem;
  margin-bottom: 30px;
  line-height: 1.3;
}

.wiki-logo a {
  color: #202122;
  text-decoration: none;
}

.wiki-logo a:hover {
  color: #0645ad;
}

.wiki-nav h2 {
  font-size: 0.9rem;
  text-transform: uppercase;
  color: #54595d;
  margin-bottom: 10px;
  font-weight: 600;
}

.wiki-nav ul {
  list-style: none;
}

.wiki-nav li {
  margin-bottom: 8px;
}

.wiki-nav li.active {
  font-weight: bold;
}

.wiki-nav a {
  color: #0645ad;
  text-decoration: none;
  font-size: 0.95rem;
}

.wiki-nav a:hover {
  text-decoration: underline;
}

.wiki-footer {
  margin-top: 40px;
  padding-top: 20px;
  border-top: 1px solid #eaecf0;
  font-size: 0.85rem;
  color: #72777d;
}

/* Main content area */
.wiki-content {
  margin-left: 280px;
  flex: 1;
  padding: 40px 60px;
  max-width: 1200px;
}

/* Article styles */
article {
  background-color: #fff;
  padding: 40px;
  border: 1px solid #a2a9b1;
  border-radius: 2px;
}

article h1 {
  font-size: 2rem;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid #eaecf0;
  color: #000;
}

article h2 {
  font-size: 1.5rem;
  margin-top: 30px;
  margin-bottom: 15px;
  color: #000;
  border-bottom: 1px solid #eaecf0;
  padding-bottom: 5px;
}

article h3 {
  font-size: 1.2rem;
  margin-top: 25px;
  margin-bottom: 10px;
  color: #000;
}

article p {
  margin-bottom: 15px;
  line-height: 1.6;
}

article ul, article ol {
  margin-left: 30px;
  margin-bottom: 15px;
}

article li {
  margin-bottom: 8px;
}

article a {
  color: #0645ad;
  text-decoration: none;
}

article a:hover {
  text-decoration: underline;
}

article a:visited {
  color: #0b0080;
}

article strong {
  font-weight: 600;
}

article code {
  background-color: #f8f9fa;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: "Courier New", monospace;
  font-size: 0.9em;
}

article pre {
  background-color: #f8f9fa;
  padding: 15px;
  border: 1px solid #eaecf0;
  border-radius: 3px;
  overflow-x: auto;
  margin-bottom: 15px;
}

article pre code {
  background-color: transparent;
  padding: 0;
}

article blockquote {
  border-left: 4px solid #eaecf0;
  padding-left: 20px;
  margin: 20px 0;
  color: #54595d;
  font-style: italic;
}

article hr {
  border: none;
  border-top: 1px solid #eaecf0;
  margin: 30px 0;
}

/* Responsive design */
@media (max-width: 768px) {
  .wiki-sidebar {
    width: 100%;
    height: auto;
    position: relative;
    border-right: none;
    border-bottom: 1px solid #a2a9b1;
  }
  
  .wiki-content {
    margin-left: 0;
    padding: 20px;
  }
  
  article {
    padding: 20px;
  }
}
`;
}
