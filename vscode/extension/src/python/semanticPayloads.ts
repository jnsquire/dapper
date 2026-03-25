export type PythonToolCompletionStatus = 'complete' | 'partial' | 'failed' | 'timed-out';

export type PythonSymbolKind = 'function' | 'method' | 'class' | 'variable' | 'parameter' | 'constant';

export interface PythonOutputBudget {
  requestedLimit?: number;
  appliedLimit?: number;
  requestedOffset?: number;
  appliedOffset?: number;
  returnedItems: number;
  totalItems: number;
  truncated: boolean;
  nextOffset?: number;
}

export interface PythonTypeInfo {
  declaredType?: string;
  inferredType?: string;
  symbolKind?: PythonSymbolKind;
  source: 'ty' | 'fallback';
}

export interface PythonSignatureParameter {
  name: string;
  kind?: 'positional-only' | 'positional-or-keyword' | 'keyword-only' | 'vararg' | 'kwargs';
  type?: string;
  defaultValue?: string;
  optional?: boolean;
}

export interface PythonCallSignature {
  label?: string;
  parameters: PythonSignatureParameter[];
  returnType?: string;
  overloadIndex?: number;
  activeParameter?: number;
}

export interface PythonDocumentation {
  format?: 'plaintext' | 'markdown';
  summary?: string;
  docstring?: string;
}

export interface PythonRelatedLocation {
  file: string;
  startLine: number;
  startColumn?: number;
  endLine?: number;
  endColumn?: number;
  message?: string;
}

export interface PythonDiagnosticContext {
  summary?: string;
  explanation?: string;
  notes?: string[];
  relatedLocations?: PythonRelatedLocation[];
  rule?: string;
  code?: string;
}