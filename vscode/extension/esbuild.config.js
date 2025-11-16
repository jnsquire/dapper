import esbuild from 'esbuild';
import path from 'path';
import { sassPlugin } from 'esbuild-sass-plugin';
import { copy } from 'esbuild-plugin-copy';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const isProduction = process.argv.includes('--production');
const isWatch = process.argv.includes('--watch');

const commonConfig = {
  entryPoints: {
    'extension': './src/extension.ts', // Extension entry point
    'webview/views/debug/DebugView': './src/webview/views/debug/DebugView.tsx',
    'webview/views/config/ConfigView': './src/webview/views/config/ConfigView.tsx',
  },
  bundle: true,
  minify: isProduction,
  sourcemap: !isProduction,
  external: ['vscode'], // Mark vscode as external
  platform: 'node', // For the extension
  format: 'esm', // Use ES modules
  target: 'node14', // VS Code's Node.js version requirement
  outdir: 'out',
  tsconfig: './tsconfig.json',
  define: {
    'process.env.NODE_ENV': isProduction ? '"production"' : '"development"',
  },
  banner: {
    // Add banner to handle __dirname in ESM
    js: 'import { createRequire } from \'module\'; const require = createRequire(import.meta.url);\n' +
        'import { fileURLToPath } from \'url\'; import { dirname } from \'path\';\n' +
        'const __filename = fileURLToPath(import.meta.url);\n' +
        'const __dirname = dirname(__filename);',
  },
  plugins: [
    // Handle SCSS files
    sassPlugin({
      type: 'css',
      sourceMap: !isProduction,
    }),
    // Copy static assets
    copy({
      assets: [
        {
          from: ['./src/**/*.css'],
          to: ['./'],
          keepStructure: true,
        },
      ],
    }),
  ],
};

// Extension build (Node.js)
async function buildExtension() {
  await esbuild.build({
    ...commonConfig,
    platform: 'node',
    format: 'esm',
    outdir: 'out',
    entryPoints: {
      'extension': './src/extension.ts',
      'debugAdapter/dapperDebugAdapter': './src/debugAdapter/dapperDebugAdapter.ts',
      'debugAdapter/configurationProvider': './src/debugAdapter/configurationProvider.ts',
      'webview/reactSSRProvider': './src/webview/reactSSRProvider.ts',
    },
  // Keep vscode and native debug adapter external (resolved at runtime by VS Code)
  external: ['vscode', '@vscode/debugadapter'],
    banner: {
      ...commonConfig.banner,
      // Ensure Node.js can handle ES modules with dynamic imports
      js: `import { createRequire } from 'module';
           const require = createRequire(import.meta.url);
           import { fileURLToPath } from 'url';
           import { dirname } from 'path';
           const __filename = fileURLToPath(import.meta.url);
           const __dirname = dirname(__filename);`
    },
    // Ensure proper file extensions in imports
    outExtension: { '.js': '.mjs' },
  });
}

// Webview build (Browser)
const buildWebview = async () => {
  return esbuild.build({
    ...commonConfig,
    entryPoints: {
      'webview/views/debug/DebugView': './src/webview/views/debug/DebugView.tsx',
      'webview/views/config/ConfigView': './src/webview/views/config/ConfigView.tsx',
    },
    platform: 'browser',
    format: 'esm',
    outbase: './src',
    outdir: 'out/compiled',
    target: ['es2020'],
    jsx: 'automatic',
    jsxImportSource: 'react',
    loader: {
      '.ts': 'tsx', // Treat .ts files as TSX
      '.tsx': 'tsx',
      '.js': 'jsx',
      '.jsx': 'jsx',
    },
    bundle: true,
    minify: isProduction,
    sourcemap: !isProduction,
  // Externalize vscode and the vscode-elements package so they are not bundled into the webview
  external: ['vscode', '@vscode-elements/elements', '@vscode-elements/elements/dist/vscode-elements.js'],
    define: {
      'process.env.NODE_ENV': isProduction ? '"production"' : '"development"',
    },
  });
};

// Build both extension and webview
async function buildAll() {
  try {
    await Promise.all([
      buildExtension(),
      buildWebview(),
    ]);
    console.log('Build completed successfully');
  } catch (error) {
    console.error('Build failed:', error);
    process.exit(1);
  }
}

// Watch mode
if (isWatch) {
  const context = await esbuild.context(commonConfig);
  await context.watch();
  console.log('Watching for changes...');
} else {
  buildAll();
}
