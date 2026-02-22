import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
	cacheDir: 'node_modules/.vitest',
	resolve: {
		alias: {
			vscode: path.resolve(__dirname, 'test', '__mocks__', 'vscode.mjs')
		}
	},
	test: {
		environment: 'node',
		globals: true,
		include: ['test/**/*.test.{js,ts,tsx}']
	}
});
