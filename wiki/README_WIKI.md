# Things the Humans Should Know - Wiki Project

A Wikipedia-style knowledge base built with **TypeScript** and **Bun**, dedicated to documenting essential information that every human should understand about the world, science, society, and ourselves.

## 🌟 Features

- **📝 Markdown-based content** - Write articles in simple Markdown format
- **🎨 Wikipedia-inspired design** - Clean, familiar interface with sidebar navigation
- **⚡ Lightning-fast builds** - Powered by Bun runtime
- **🔄 Auto-rebuild on changes** - Development mode watches for file changes
- **🌐 Simple HTTP server** - Built-in server or deploy static files
- **📱 Responsive design** - Works seamlessly on all devices
- **🔗 Internal linking** - Easy cross-references between articles
- **🚀 VPS-ready** - Designed for deployment on any VPS

## 📦 Project Structure

This repository contains both the original Dapper project (Python debugger) and the new wiki project:

```
dapper/                    # Root repository
├── wiki/                 # → The wiki project (this)
│   ├── content/
│   │   └── articles/    # Markdown articles
│   ├── src/             # TypeScript source
│   ├── dist/            # Generated static site
│   ├── README.md        # Wiki documentation
│   └── DEPLOYMENT.md    # Deployment guide
├── dapper/              # Original Python debugger
├── tests/               # Python tests
└── ...                  # Other Python project files
```

## 🚀 Quick Start

### Prerequisites

Install [Bun](https://bun.sh) (fast JavaScript runtime):

```bash
curl -fsSL https://bun.sh/install | bash
```

### Installation

```bash
# Navigate to wiki directory
cd wiki

# Install dependencies
bun install
```

### Development

Run with auto-rebuild on file changes:

```bash
bun run dev
```

Visit: http://localhost:3000

### Build

Generate static site:

```bash
bun run build
```

Output will be in `dist/` directory.

### Production

Run the server (production mode):

```bash
bun run start
```

## 📚 Current Articles

The wiki includes these foundational articles:

- **Home** - Introduction and overview
- **The Scientific Method** - How we learn about the world
- **Critical Thinking** - Essential skills for reasoning
- **Climate Science** - Understanding our planet's systems
- **Digital Privacy** - Protecting yourself online

## ✍️ Adding Content

### Create a New Article

1. Create a markdown file in `content/articles/`:

```bash
cd wiki/content/articles
nano your-article-name.md
```

2. Write your article using Markdown:

```markdown
# Your Article Title

Introduction paragraph...

## Section 1

Content here...

## Related Topics

- [Another Article](another-article)
- [Scientific Method](scientific-method)

---

*Last updated: 2025*
```

3. Build and preview:

```bash
cd ../..
bun run dev
```

The article automatically appears in the navigation!

### Linking Between Articles

Use relative links without file extensions:

```markdown
Learn more about [Critical Thinking](critical-thinking).
```

## 🌐 Deployment

### Deploy to a VPS

See the comprehensive [DEPLOYMENT.md](wiki/DEPLOYMENT.md) guide for detailed instructions.

**Quick version:**

1. **SSH into your VPS** and install Bun
2. **Clone the repository**
3. **Build the site**: `cd wiki && bun install && bun run build`
4. **Start the server**: `PORT=80 bun run start`
5. **(Optional)** Set up Nginx as reverse proxy
6. **(Optional)** Add SSL with Let's Encrypt

### Static Deployment

The `dist/` directory contains all static files and can be served by any HTTP server:

- Nginx
- Apache
- Any static hosting service

## 🛠️ Technology Stack

- **[Bun](https://bun.sh)** - Fast all-in-one JavaScript runtime
- **TypeScript** - Type-safe JavaScript for reliability
- **[marked](https://marked.js.org/)** - Fast markdown parser
- **Custom build system** - Static site generator
- **Built-in HTTP server** - No external dependencies needed

## 📖 Documentation

- **[wiki/README.md](wiki/README.md)** - Detailed wiki documentation
- **[wiki/DEPLOYMENT.md](wiki/DEPLOYMENT.md)** - Complete deployment guide
- **[README.md](README.md)** - This file (project overview)

## 🎯 Project Goals

This wiki aims to:

1. **Document essential knowledge** - Topics every human should understand
2. **Make information accessible** - Clear, jargon-free explanations
3. **Encourage learning** - Well-organized, interlinked content
4. **Be easy to maintain** - Simple Markdown files, straightforward build
5. **Deploy anywhere** - Run on any VPS with minimal setup

## 🤝 Contributing

To add or improve content:

1. **Edit articles** in `wiki/content/articles/`
2. **Test locally** with `bun run dev`
3. **Commit changes** to git
4. **Deploy** by rebuilding on your VPS

## 📋 Available Scripts

From the `wiki/` directory:

```bash
bun run build    # Build static site
bun run dev      # Development mode with watch
bun run start    # Production server
bun run serve    # Alias for start
```

## 🔧 Configuration

Edit `wiki/src/build.ts` to customize:

- Site title and description
- Directory paths
- Build behavior

Edit `wiki/src/template.ts` to customize:

- HTML structure
- CSS styling
- Page layout

## 📝 Content Guidelines

When writing articles:

- **Clear and accessible** - Write for a general audience
- **Well-researched** - Use reliable sources
- **Properly structured** - Use headings, lists, sections
- **Cross-referenced** - Link to related topics
- **Regularly updated** - Note when information changes

## 🔒 Security

- Build artifacts (`dist/`, `node_modules/`) are gitignored
- No user-generated content (static site)
- Follow deployment security best practices
- Keep dependencies updated: `bun update`

## 💡 Future Enhancements

Potential improvements:

- [ ] Search functionality
- [ ] Category/tag system
- [ ] Table of contents for long articles
- [ ] Dark mode toggle
- [ ] Print-friendly styling
- [ ] RSS feed for updates
- [ ] Multi-language support

## 📄 License

MIT License - See root repository LICENSE file

## 🙏 Acknowledgments

- **Wikipedia** - Design inspiration
- **Bun team** - Amazing runtime
- **marked** - Excellent markdown parser

## 📞 Support

For questions or issues:

- Check the [wiki README](wiki/README.md)
- Review the [deployment guide](wiki/DEPLOYMENT.md)
- Consult [Bun documentation](https://bun.sh/docs)

---

**Built with ❤️ using TypeScript and Bun**
