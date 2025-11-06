# Things the Humans Should Know - Wiki

A Wikipedia-style knowledge base built with TypeScript and Bun, containing essential information that every human should understand about the world, science, society, and ourselves.

## Features

- 📝 **Markdown-based content** - Write articles in simple Markdown
- 🎨 **Wikipedia-inspired design** - Clean, familiar interface
- ⚡ **Fast static site generation** - Built with Bun for speed
- 🔄 **Auto-rebuild on changes** - Watch mode for development
- 🌐 **Simple HTTP server** - Serve static content efficiently
- 📱 **Responsive design** - Works on all devices

## Prerequisites

- [Bun](https://bun.sh) - Fast JavaScript runtime and toolkit
  ```bash
  curl -fsSL https://bun.sh/install | bash
  ```

## Installation

1. Navigate to the wiki directory:
   ```bash
   cd wiki
   ```

2. Install dependencies:
   ```bash
   bun install
   ```

## Usage

### Development Mode

Run with auto-rebuild on file changes:

```bash
bun run dev
```

This will:
- Build the static site from markdown files
- Start a local HTTP server on port 3000
- Watch for changes and rebuild automatically

Visit: http://localhost:3000

### Production Build

Build the static site:

```bash
bun run build
```

Output will be in the `dist/` directory.

### Production Server

Start the server without watch mode:

```bash
bun run start
```

or

```bash
bun run serve
```

## Project Structure

```
wiki/
├── content/
│   └── articles/          # Markdown articles go here
│       ├── home.md        # Homepage content
│       ├── scientific-method.md
│       └── critical-thinking.md
├── dist/                  # Generated static files (gitignored)
├── src/
│   ├── build.ts          # Build system
│   ├── server.ts         # HTTP server
│   ├── markdown.ts       # Markdown parser
│   ├── template.ts       # HTML templates and styles
│   └── types.ts          # TypeScript types
├── package.json
└── README.md
```

## Adding Content

### Create a New Article

1. Create a new `.md` file in `content/articles/`:
   ```bash
   touch content/articles/my-new-article.md
   ```

2. Write your article using Markdown:
   ```markdown
   # My New Article

   Introduction paragraph...

   ## Section 1

   Content here...

   ## Related Topics

   - [Another Article](another-article)
   - [Scientific Method](scientific-method)

   ---

   *Last updated: 2025*
   ```

3. The article will automatically appear in the navigation sidebar

### Linking Between Articles

Use relative links without the `.html` extension:

```markdown
See [Critical Thinking](critical-thinking) for more information.
```

This will be automatically converted to the proper HTML link.

## Customization

### Styling

Edit the `generateStyles()` function in `src/template.ts` to customize the appearance.

### Template

Modify the `renderPage()` function in `src/template.ts` to change the HTML structure.

### Configuration

Edit the `config` object in `src/build.ts` to change:
- Site title and description
- Directory paths
- Build behavior

## Deployment

### Deploy to a VPS

1. Build the static site:
   ```bash
   bun run build
   ```

2. Copy the `dist/` directory to your VPS

3. Serve with any HTTP server (nginx, Apache, or Bun):
   ```bash
   # Using Bun
   PORT=80 bun run serve
   
   # Or use nginx/Apache to serve the dist/ directory
   ```

### Environment Variables

- `PORT` - Server port (default: 3000)

Example:
```bash
PORT=8080 bun run start
```

## Technology Stack

- **Runtime**: [Bun](https://bun.sh) - Fast JavaScript runtime
- **Language**: TypeScript - Type-safe JavaScript
- **Markdown Parser**: [marked](https://marked.js.org/) - Convert markdown to HTML
- **Server**: Built-in Bun HTTP server

## Development

### File Watching

In development mode, the build system watches for changes in the `content/articles/` directory and automatically rebuilds the site.

### Build Process

1. Load all markdown files from `content/articles/`
2. Parse markdown and extract metadata (title, last updated)
3. Convert markdown to HTML
4. Process internal links
5. Render HTML using templates
6. Generate CSS
7. Write static files to `dist/`

## Contributing

To add new articles:

1. Create a markdown file in `content/articles/`
2. Follow the existing article format
3. Include proper headings and sections
4. Link to related articles
5. Test locally with `bun run dev`

## License

MIT

## About

This wiki is dedicated to documenting essential knowledge that every human should have - from science and critical thinking to history, technology, and philosophy. The goal is to provide clear, accurate, and accessible information on topics that truly matter.
