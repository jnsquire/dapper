import { describe, it, expect } from 'vitest';
import * as React from 'react';
import { renderToString } from 'react-dom/server';
import { VariableInspector } from '../src/ui/components/VariableInspector.js';

interface Variable {
	name: string;
	type: string;
	value: string;
	variablesReference: number;
	children?: Variable[];
}

const makeVariable = (overrides: Partial<Variable> = {}): Variable => ({
	name: 'x',
	type: 'int',
	value: '42',
	variablesReference: 0,
	...overrides,
});

describe('VariableInspector', () => {
	// --- Rendering ---

	describe('rendering', () => {
		it('should render empty state message when no variables', () => {
			const html = renderToString(
				React.createElement(VariableInspector, { variables: [] }),
			);
			expect(html).toContain('No variables in scope');
		});

		it('should render variable names', () => {
			const html = renderToString(
				React.createElement(VariableInspector, {
					variables: [makeVariable({ name: 'myVar' })],
				}),
			);
			expect(html).toContain('myVar');
		});

		it('should render variable types', () => {
			const html = renderToString(
				React.createElement(VariableInspector, {
					variables: [makeVariable({ type: 'str' })],
				}),
			);
			expect(html).toContain('str');
		});

		it('should render variable values', () => {
			const html = renderToString(
				React.createElement(VariableInspector, {
					variables: [makeVariable({ value: '"hello"' })],
				}),
			);
			expect(html).toContain('&quot;hello&quot;');
		});

		it('should render multiple variables', () => {
			const variables: Variable[] = [
				makeVariable({ name: 'alpha' }),
				makeVariable({ name: 'beta' }),
				makeVariable({ name: 'gamma' }),
			];
			const html = renderToString(
				React.createElement(VariableInspector, { variables }),
			);
			expect(html).toContain('alpha');
			expect(html).toContain('beta');
			expect(html).toContain('gamma');
		});

		it('should render expand icon for variables with children', () => {
			const html = renderToString(
				React.createElement(VariableInspector, {
					variables: [
						makeVariable({
							name: 'parent',
							variablesReference: 1,
							children: [makeVariable({ name: 'child' })],
						}),
					],
				}),
			);
			expect(html).toContain('►');
		});

		it('should not render expand icon for leaf variables', () => {
			const html = renderToString(
				React.createElement(VariableInspector, {
					variables: [makeVariable({ variablesReference: 0 })],
				}),
			);
			expect(html).not.toContain('►');
			expect(html).not.toContain('▼');
		});

		it('should render the header', () => {
			const html = renderToString(
				React.createElement(VariableInspector, { variables: [] }),
			);
			expect(html).toContain('Variables');
		});

		it('should handle undefined variables prop gracefully', () => {
			expect(() => {
				const html = renderToString(
					React.createElement(VariableInspector, {
						variables: undefined as any,
					}),
				);
				// Should fall back to default empty array and show empty state
				expect(html).toContain('No variables in scope');
			}).not.toThrow();
		});
	});

	// --- Structure ---

	describe('structure', () => {
		it('should render variable-inspector class', () => {
			const html = renderToString(
				React.createElement(VariableInspector, { variables: [] }),
			);
			expect(html).toContain('variable-inspector');
		});

		it('should render variable-list class', () => {
			const html = renderToString(
				React.createElement(VariableInspector, { variables: [] }),
			);
			expect(html).toContain('variable-list');
		});

		it('should apply depth-based indentation', () => {
			const parentVar = makeVariable({
				name: 'parent',
				variablesReference: 1,
				children: [
					makeVariable({ name: 'child', variablesReference: 0 }),
				],
			});

			// In the initial SSR render, children are not expanded (expandedVars starts empty).
			// The top-level variable should have marginLeft: 0px (depth 0).
			const html = renderToString(
				React.createElement(VariableInspector, {
					variables: [parentVar],
				}),
			);
			expect(html).toMatch(/margin-left:\s*0px/);
		});

		it('should render variable-header class for each variable', () => {
			const html = renderToString(
				React.createElement(VariableInspector, {
					variables: [makeVariable(), makeVariable({ name: 'y' })],
				}),
			);
			// Should have at least two variable-header instances
			const matches = html.match(/variable-header/g);
			expect(matches).not.toBeNull();
			expect(matches!.length).toBeGreaterThanOrEqual(2);
		});

		it('should render variable-name class', () => {
			const html = renderToString(
				React.createElement(VariableInspector, {
					variables: [makeVariable()],
				}),
			);
			expect(html).toContain('variable-name');
		});

		it('should render variable-type class', () => {
			const html = renderToString(
				React.createElement(VariableInspector, {
					variables: [makeVariable()],
				}),
			);
			expect(html).toContain('variable-type');
		});

		it('should render variable-value class', () => {
			const html = renderToString(
				React.createElement(VariableInspector, {
					variables: [makeVariable()],
				}),
			);
			expect(html).toContain('variable-value');
		});
	});
});
