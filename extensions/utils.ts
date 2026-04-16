/**
 * File parsing utilities for canary extensions.
 * Handles C/C++ source parsing, opt.yaml remark parsing, and
 * SEARCH/REPLACE application.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { exec } from 'node:child_process';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FunctionInfo {
  name: string;
  signature: string;
  body: string;
  fullText: string;
  startLine: number; // 1-indexed
  endLine: number;   // 1-indexed
}

export interface CompileResult {
  success: boolean;
  stdout: string;
  stderr: string;
}

export interface ValidatorResult {
  pass: boolean;
  runtimeS: number | null;
  errorMessage: string;
}

export interface SearchReplaceBlock {
  search: string;
  replace: string;
}

// ---------------------------------------------------------------------------
// Source file discovery
// ---------------------------------------------------------------------------

/** Find the primary C/C++ source file in a benchmark directory. */
export function findSourceFile(benchPath: string): string | null {
  const exts = ['.c', '.cpp', '.cxx', '.cc'];
  const entries = fs.readdirSync(benchPath);

  for (const ext of exts) {
    const matches = entries.filter(e => e.endsWith(ext) && !e.endsWith('.bak'));
    if (matches.length === 1) return path.join(benchPath, matches[0]);
    if (matches.length > 1) {
      // Prefer file without 'test'/'main' in name
      const preferred = matches.find(f => !f.includes('test') && !f.includes('main'));
      return path.join(benchPath, preferred ?? matches[0]);
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// C/C++ function extraction
// ---------------------------------------------------------------------------

const FUNC_SIG_RE =
  /^(?:static\s+|inline\s+|extern\s+)?[\w\s*&:<>,]+\s+(\w+)\s*\([^)]*\)(?:\s*const)?(?:\s*\{|\s*$)/;
const SKIP_KEYWORDS = new Set(['if', 'for', 'while', 'switch', 'return', 'sizeof', 'catch']);

/** Count occurrences of a character in a string. */
function countChar(s: string, ch: string): number {
  let n = 0;
  for (const c of s) if (c === ch) n++;
  return n;
}

/** Extract a named function definition from source text. Returns null if not found. */
export function extractFunction(source: string, funcName: string): FunctionInfo | null {
  const lines = source.split('\n');

  for (let i = 0; i < lines.length; i++) {
    const stripped = lines[i].trim();
    if (!stripped || stripped.startsWith('#') || stripped.startsWith('//')) continue;

    const match = FUNC_SIG_RE.exec(stripped);
    if (!match || match[1] !== funcName || SKIP_KEYWORDS.has(match[1])) continue;

    // Find opening brace (on current line or within next 3)
    let braceLineIdx = i;
    let foundBrace = lines[i].includes('{');

    if (!foundBrace) {
      for (let j = i + 1; j < Math.min(i + 4, lines.length); j++) {
        if (lines[j].includes('{')) { braceLineIdx = j; foundBrace = true; break; }
        const s = lines[j].trim();
        if (s && !s.startsWith('//') && s !== '{') break;
      }
    }
    if (!foundBrace) continue;

    let braceCount = countChar(lines[braceLineIdx], '{') - countChar(lines[braceLineIdx], '}');
    let j = braceLineIdx + 1;
    while (j < lines.length && braceCount > 0) {
      braceCount += countChar(lines[j], '{') - countChar(lines[j], '}');
      j++;
    }

    const endLine = j - 1;
    return {
      name: funcName,
      signature: lines[i].trim(),
      body: lines.slice(braceLineIdx + 1, endLine).join('\n'),
      fullText: lines.slice(i, endLine + 1).join('\n'),
      startLine: i + 1,
      endLine: endLine + 1,
    };
  }
  return null;
}

/** Prepend line numbers to function text (1-indexed from startLine). */
export function numberLines(text: string, startLine: number): string {
  return text
    .split('\n')
    .map((line, i) => `${startLine + i}: ${line}`)
    .join('\n');
}

// ---------------------------------------------------------------------------
// File context extraction (types, includes, declarations — no function bodies)
// ---------------------------------------------------------------------------

/** Extract type definitions, includes, and function declarations from source. */
export function extractFileContext(source: string): string {
  const lines = source.split('\n');
  const out: string[] = [];
  let i = 0;
  let inMLC = false; // in multi-line comment

  while (i < lines.length) {
    let stripped = lines[i].trim();

    // Multi-line comment tracking
    if (inMLC) {
      if (stripped.includes('*/')) {
        inMLC = false;
        stripped = stripped.slice(stripped.indexOf('*/') + 2).trim();
      } else { i++; continue; }
    }
    if (stripped.includes('/*') && !stripped.includes('*/')) {
      inMLC = true;
      stripped = stripped.slice(0, stripped.indexOf('/*')).trim();
    }

    if (!stripped || stripped.startsWith('//')) { i++; continue; }

    // Preprocessor
    if (lines[i].trimStart().startsWith('#')) {
      out.push(lines[i]);
      while (i < lines.length - 1 && lines[i].trimEnd().endsWith('\\')) {
        i++;
        out.push(lines[i]);
      }
      i++;
      continue;
    }

    // typedef
    if (stripped.startsWith('typedef')) {
      const block = [lines[i]];
      while (i < lines.length - 1 && !lines[i].includes(';')) { i++; block.push(lines[i]); }
      out.push(...block);
      i++;
      continue;
    }

    // struct / class / enum / union
    if (/^(struct|class|enum|union)\b/.test(stripped)) {
      if (stripped.includes(';') && !stripped.includes('{')) {
        out.push(lines[i]); i++; continue;
      }
      const block = [lines[i]];
      let j = i;
      while (j < lines.length && !lines[j].includes('{')) { j++; block.push(lines[j]); }
      if (j < lines.length) {
        let bc = countChar(lines[j], '{') - countChar(lines[j], '}');
        j++;
        while (j < lines.length && bc > 0) {
          block.push(lines[j]);
          bc += countChar(lines[j], '{') - countChar(lines[j], '}');
          j++;
        }
        out.push(...block);
        i = j;
        continue;
      }
    }

    // using / namespace
    if (stripped.startsWith('using') || stripped.startsWith('namespace')) {
      out.push(lines[i]); i++; continue;
    }

    // Function declarations vs definitions
    if (stripped.includes('(') && stripped.includes(')') &&
        !/^(if|for|while|switch|sizeof|catch)\b/.test(stripped)) {
      const sig = [lines[i]];
      let j = i;
      let pd = 0;
      let done = false;
      while (j < lines.length && !done) {
        for (const ch of lines[j]) {
          if (ch === '(') pd++;
          else if (ch === ')') pd--;
          else if ((ch === ';' || ch === '{') && pd === 0) { done = true; break; }
        }
        if (!done && j < lines.length - 1) { j++; sig.push(lines[j]); } else break;
      }
      const combined = sig.join(' ');
      const hasS = combined.includes(';');
      const hasB = combined.includes('{');
      if (hasS && (!hasB || combined.indexOf(';') < combined.indexOf('{'))) {
        out.push(...sig); i = j + 1; continue;
      } else if (hasB) {
        // skip function definition body
        let bc = 0;
        for (const ln of sig) bc += countChar(ln, '{') - countChar(ln, '}');
        j++;
        while (j < lines.length && bc > 0) {
          bc += countChar(lines[j], '{') - countChar(lines[j], '}');
          j++;
        }
        i = j; continue;
      }
    }

    i++;
  }

  return out.join('\n');
}

// ---------------------------------------------------------------------------
// Remark file discovery and parsing
// ---------------------------------------------------------------------------

/** Find .opt.yaml / .optrpt files in bench directory for the given source file. */
export function findRemarkFiles(benchPath: string, sourceFile: string): string[] {
  const prefix = path.basename(sourceFile, path.extname(sourceFile));
  return fs.readdirSync(benchPath)
    .filter(e => e.startsWith(prefix) && (e.endsWith('.opt.yaml') || e.endsWith('.optrpt')))
    .map(e => path.join(benchPath, e));
}

/** Delete old remark files before recompilation. */
export function cleanRemarkFiles(benchPath: string): void {
  for (const entry of fs.readdirSync(benchPath)) {
    if (entry.endsWith('.opt.yaml') || entry.endsWith('.optrpt')) {
      try { fs.unlinkSync(path.join(benchPath, entry)); } catch { /* ignore */ }
    }
  }
}

/** Read remark files and return raw YAML content for the given function. */
export function parseRemarksForFunction(remarkFiles: string[], funcName: string): string {
  const results: string[] = [];

  for (const file of remarkFiles) {
    if (!fs.existsSync(file)) continue;
    const content = fs.readFileSync(file, 'utf-8');

    // Split on YAML document separators
    const docs = content.split(/^---[ \t]*/m).filter(d => d.trim());

    for (const doc of docs) {
      const funcMatch = doc.match(/Function:\s+(\S+)/);
      if (!funcMatch) continue;

      // Accept exact match or mangled name containing funcName
      const docFunc = funcMatch[1];
      if (docFunc !== funcName && !docFunc.includes(funcName)) continue;

      // Only vectorization-related passes
      const passMatch = doc.match(/Pass:\s+(\S+)/);
      const pass = passMatch?.[1] ?? '';
      const vecPasses = ['loop-vectorize', 'slp-vectorizer', 'loop-unroll', 'vectorize'];
      if (!vecPasses.some(p => pass.includes(p))) continue;

      results.push('--- ' + doc.trim());
    }
  }

  return results.join('\n\n');
}

// ---------------------------------------------------------------------------
// Diagnostic ablation
// ---------------------------------------------------------------------------

/**
 * Ablate remark content according to the PLAN.md level definition:
 *   0 → remark type only
 *   1 → + message string
 *   2 → + source location
 *   3 → + optimization name
 *   4 → + analysis details
 *   5 → full remark (no stripping)
 */
export function ablateRemarks(rawContent: string, level: number): string {
  if (level >= 5) return rawContent;
  if (!rawContent.trim()) return '';

  const docs = rawContent.split(/^---[ \t]*/m).filter(d => d.trim());
  const ablated: string[] = [];

  for (const doc of docs) {
    const typeMatch = doc.match(/^!(\w+)/);
    const nameMatch = doc.match(/Name:\s+(\S+)/);
    const debugLocMatch = doc.match(
      /DebugLoc:\s*\{[^}]*File:\s*([^,}]+)[,}][^}]*Line:\s*(\d+)[^}]*Column:\s*(\d+)/,
    );
    const argStrings = [...doc.matchAll(/- String:\s+['"]?([^'"\n]+)['"]?/g)].map(m => m[1].trim());

    const remarkType = typeMatch ? typeMatch[1] : 'Remark';
    const parts: string[] = [`${remarkType} remark`];

    if (level >= 1 && argStrings.length > 0) {
      parts.push(`Message: ${argStrings[0]}`);
    }
    if (level >= 2 && debugLocMatch) {
      parts.push(`Location: ${debugLocMatch[1].trim()}:${debugLocMatch[2]}:${debugLocMatch[3]}`);
    }
    if (level >= 3 && nameMatch) {
      parts.push(`Optimization: ${nameMatch[1]}`);
    }
    if (level >= 4 && argStrings.length > 1) {
      parts.push(`Details: ${argStrings.slice(1).join('; ')}`);
    }

    ablated.push(parts.join('\n'));
  }

  return ablated.join('\n\n');
}

/** Check for vectorization success in remark content. */
export function checkVectorizationSuccess(remarkContent: string, isClang: boolean): boolean {
  if (isClang) return remarkContent.includes('!Passed');
  return /was vectorized/i.test(remarkContent);
}

// ---------------------------------------------------------------------------
// SEARCH/REPLACE parsing and application
// ---------------------------------------------------------------------------

/** Parse all SEARCH/REPLACE blocks from LLM output text. */
export function parseSearchReplace(text: string): SearchReplaceBlock[] {
  const blocks: SearchReplaceBlock[] = [];
  const re = /<<<<<<< SEARCH\n([\s\S]*?)\n=======\n([\s\S]*?)\n>>>>>>> REPLACE/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    blocks.push({ search: m[1], replace: m[2] });
  }
  return blocks;
}

/** Apply a SEARCH/REPLACE block to source text. Returns null if search not found. */
export function applySearchReplace(source: string, block: SearchReplaceBlock): string | null {
  // Exact match
  if (source.includes(block.search)) {
    return source.replace(block.search, block.replace);
  }

  // Whitespace-normalized line-by-line match
  const normalize = (s: string) =>
    s.replace(/[ \t]+/g, ' ').replace(/\n[ \t]+/g, '\n').trim();

  const sourceLines = source.split('\n');
  const searchLines = block.search.split('\n');
  const normSearch = normalize(block.search);

  for (let i = 0; i <= sourceLines.length - searchLines.length; i++) {
    const candidate = sourceLines.slice(i, i + searchLines.length).join('\n');
    if (normalize(candidate) === normSearch) {
      const before = sourceLines.slice(0, i).join('\n');
      const after = sourceLines.slice(i + searchLines.length).join('\n');
      return (before ? before + '\n' : '') + block.replace + (after ? '\n' + after : '');
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// Compilation
// ---------------------------------------------------------------------------

/** Run make in bench directory (shell: true to support complex make commands). */
export function runMake(benchPath: string, makeCommand: string): Promise<CompileResult> {
  return new Promise(resolve => {
    exec(makeCommand, { cwd: benchPath, timeout: 60_000 }, (err, stdout, stderr) => {
      resolve({ success: !err, stdout, stderr });
    });
  });
}

/** Extract compilation errors relevant to a function's line range. */
export function extractCompileErrors(
  stderr: string,
  sourceFile: string,
  startLine: number,
  endLine: number,
): string {
  const fileName = path.basename(sourceFile);
  const lines = stderr.split('\n');
  const relevant: string[] = [];

  for (const line of lines) {
    if (!line.includes(fileName)) {
      // Include context lines that follow a match
      if (relevant.length > 0 && line.startsWith(' ')) relevant.push(line);
      continue;
    }
    const lineMatch = line.match(/:(\d+):/);
    if (lineMatch) {
      const errLine = parseInt(lineMatch[1]);
      if (errLine >= startLine - 5 && errLine <= endLine + 5) relevant.push(line);
    } else {
      relevant.push(line);
    }
  }

  if (relevant.length > 0) return relevant.join('\n');
  // Fallback: first 2000 chars of stderr
  return stderr.slice(0, 2000);
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/**
 * Invoke a validator via the canary validator contract:
 *   stdin  → JSON { bench_path, target_function, make_command, source_file }
 *   stdout → optionally "RUNTIME_S: <value>"
 *   exit 0 → pass (semantic equivalence confirmed)
 *   exit 1 → fail (semantic divergence)
 *   exit 2 → error (build/exec failed)
 *
 * The validatorCmd may be a full shell command (e.g. "python3 /path/to/validate.py").
 */
export function runValidator(
  validatorCmd: string,
  benchPath: string,
  targetFunction: string,
  makeCommand: string,
  sourceFile: string,
): Promise<ValidatorResult> {
  return new Promise(resolve => {
    const input = JSON.stringify({ bench_path: benchPath, target_function: targetFunction, make_command: makeCommand, source_file: sourceFile });

    const child = exec(validatorCmd, { timeout: 120_000 }, (err, stdout) => {
      // err.code may be a number (process exit code) or string (system errno).
      // Treat any non-number or non-zero code as failure.
      const rawCode = err?.code;
      const code: number = typeof rawCode === 'number' ? rawCode : (err ? 1 : 0);
      const runtimeMatch = stdout.match(/RUNTIME_S:\s*([\d.]+)/);
      resolve({
        pass: code === 0,
        runtimeS: runtimeMatch ? parseFloat(runtimeMatch[1]) : null,
        errorMessage:
          code === 2 ? 'Validator build/exec error'
          : code !== 0 ? 'Semantic divergence detected'
          : '',
      });
    });

    child.stdin?.write(input);
    child.stdin?.end();
  });
}
