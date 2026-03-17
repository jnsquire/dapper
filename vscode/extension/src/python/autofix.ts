import type { RuffAutofixOptions, RuffRunnerService, RuffWriteResult } from './ruffRunner.js';

const MAX_DIFF_BYTES = 32_768;

export interface PythonAutofixOptions extends RuffAutofixOptions {}

export interface AutofixDiffSummary {
  filesAffected: number;
  files: string[];
  totalDiffBytes: number;
  truncated: boolean;
}

export interface PythonAutofixResult extends RuffWriteResult {
  mode: 'autofix';
  diffSummary?: AutofixDiffSummary;
}

export class PythonAutofixService {
  constructor(private readonly ruffRunnerService: Pick<RuffRunnerService, 'runAutofix'>) {}

  async run(options: PythonAutofixOptions = {}): Promise<PythonAutofixResult> {
    const result = await this.ruffRunnerService.runAutofix(options);
    const diffSummary = this._buildDiffSummary(result.diff);
    return {
      ...result,
      diff: this._truncateDiff(result.diff),
      mode: 'autofix',
      diffSummary,
    };
  }

  private _buildDiffSummary(diff: string | undefined): AutofixDiffSummary | undefined {
    if (!diff) {
      return undefined;
    }
    const files = [...new Set(
      [...diff.matchAll(/^--- (.+)$/gm)].map(m => m[1].replace(/^a\//, '')),
    )];
    const totalDiffBytes = Buffer.byteLength(diff, 'utf8');
    return {
      filesAffected: files.length,
      files,
      totalDiffBytes,
      truncated: totalDiffBytes > MAX_DIFF_BYTES,
    };
  }

  private _truncateDiff(diff: string | undefined): string | undefined {
    if (!diff) {
      return undefined;
    }
    if (Buffer.byteLength(diff, 'utf8') <= MAX_DIFF_BYTES) {
      return diff;
    }
    const truncated = diff.slice(0, MAX_DIFF_BYTES);
    const lastNewline = truncated.lastIndexOf('\n');
    return (lastNewline > 0 ? truncated.slice(0, lastNewline) : truncated) + '\n... (diff truncated)';
  }
}