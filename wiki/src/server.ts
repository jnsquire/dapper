import { build, watch } from './build';

const port = parseInt(process.env.PORT || '3000');

/**
 * Start the HTTP server
 */
async function startServer(isDev: boolean = false): Promise<void> {
  // Build the site first
  await build();
  
  // Start watching if in dev mode
  if (isDev) {
    watch();
  }
  
  // Start HTTP server
  const server = Bun.serve({
    port,
    async fetch(req) {
      const url = new URL(req.url);
      let filePath = url.pathname;
      
      // Default to index.html
      if (filePath === '/') {
        filePath = '/index.html';
      }
      
      // Serve static files from dist directory
      const distPath = import.meta.dir + '/../dist' + filePath;
      const file = Bun.file(distPath);
      
      if (await file.exists()) {
        return new Response(file);
      }
      
      // 404 page
      return new Response(
        `<!DOCTYPE html>
<html>
<head>
  <title>404 - Page Not Found</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <div class="wiki-container">
    <main class="wiki-content">
      <article>
        <h1>404 - Page Not Found</h1>
        <p>The page you're looking for doesn't exist.</p>
        <p><a href="/home.html">Return to home page</a></p>
      </article>
    </main>
  </div>
</body>
</html>`,
        {
          status: 404,
          headers: { 'Content-Type': 'text/html' },
        }
      );
    },
  });
  
  console.log(`\n🌍 Server running at http://localhost:${port}`);
  console.log(`📂 Serving from: dist/`);
  if (isDev) {
    console.log('👀 Watching for changes...\n');
  }
}

// Parse command line arguments
const args = process.argv.slice(2);
const isDev = args.includes('--dev') || args.includes('-d');

startServer(isDev).catch(error => {
  console.error('Failed to start server:', error);
  process.exit(1);
});
