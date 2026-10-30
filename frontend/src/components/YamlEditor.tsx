// A YAML editor (CodeMirror 6) that checks against Kometa's schema as you type and completes keys.
// Loaded on demand: it's the biggest part of the app.

import { autocompletion, type CompletionContext, type CompletionResult } from "@codemirror/autocomplete";
import { indentWithTab } from "@codemirror/commands";
import { yaml } from "@codemirror/lang-yaml";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { forceLinting, linter, lintGutter, type Diagnostic } from "@codemirror/lint";
import { EditorView, keymap } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";

import { checkYaml, pathAt } from "../yaml/check";
import { knownKeys, loadSchema, type LoadedSchema, type SchemaKind } from "../yaml/schema";

const theme = EditorView.theme(
  {
    "&": { backgroundColor: "var(--color-bg)", color: "var(--color-text)", fontSize: "12px", borderRadius: "8px" },
    ".cm-content": { fontFamily: "var(--font-mono)", caretColor: "var(--color-accent)" },
    ".cm-gutters": { backgroundColor: "var(--color-surface)", color: "var(--color-muted)", border: "none" },
    ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "rgba(255,255,255,0.03)" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": { backgroundColor: "rgba(242,181,68,0.25)" },
    ".cm-cursor": { borderLeftColor: "var(--color-accent)" },
    ".cm-tooltip": { backgroundColor: "var(--color-surface-2)", border: "1px solid var(--color-border-strong)", color: "var(--color-text)" },
    ".cm-tooltip-autocomplete ul li[aria-selected]": { backgroundColor: "var(--color-border-strong)", color: "var(--color-text)" },
    ".cm-completionInfo": { maxWidth: "24rem" },
  },
  { dark: true },
);

const highlight = HighlightStyle.define([
  { tag: [tags.propertyName, tags.definition(tags.propertyName)], color: "var(--color-info)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--color-ok)" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--color-accent)" },
  { tag: tags.comment, color: "var(--color-muted)", fontStyle: "italic" },
  { tag: [tags.punctuation, tags.separator], color: "var(--color-muted)" },
]);

export default function YamlEditor({
  value,
  onChange,
  kind,
  label,
}: {
  value: string;
  onChange: (text: string) => void;
  kind: SchemaKind | null;
  label: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const schema = useRef<LoadedSchema | null>(null);
  const changed = useRef(onChange);
  changed.current = onChange;

  useEffect(() => {
    const check = linter(
      (editor): Diagnostic[] => checkYaml(editor.state.doc.toString(), schema.current?.validate ?? null),
      { delay: 300 },
    );
    const complete = (context: CompletionContext): CompletionResult | null => {
      const word = context.matchBefore(/[\w.]*/);
      const line = context.state.doc.lineAt(context.pos);
      const before = line.text.slice(0, context.pos - line.from);
      if (!schema.current || !word || !/^\s*(-\s+)?[\w.]*$/.test(before)) return null; // only where a key is being typed
      if (word.from === word.to && !context.explicit) return null;
      const path = pathAt(context.state.doc.toString(), context.pos);
      if (/^\s*-\s+/.test(before)) path.push(0);
      const keys = knownKeys(schema.current.root, path);
      if (keys.length === 0) return null;
      return {
        from: word.from,
        options: keys.map((key) => ({ label: key.name, type: "property", info: key.description, apply: `${key.name}: ` })),
        validFor: /^[\w.]*$/,
      };
    };
    view.current = new EditorView({
      parent: host.current!,
      doc: value,
      extensions: [
        basicSetup,
        keymap.of([indentWithTab]), // Esc, then Tab, moves focus on
        yaml(),
        theme,
        syntaxHighlighting(highlight),
        lintGutter(),
        check,
        autocompletion({ override: [complete] }),
        EditorView.contentAttributes.of({ "aria-label": label }),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) changed.current(update.state.doc.toString());
        }),
      ],
    });
    return () => view.current?.destroy();
    // Created once; later value changes are applied by the effect below.
  }, []);

  // A new value from outside (Undo my changes, reload after save) replaces the text.
  useEffect(() => {
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== value) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    let cancelled = false;
    schema.current = null;
    if (kind) {
      loadSchema(kind).then((loaded) => {
        if (cancelled || !view.current) return;
        schema.current = loaded;
        forceLinting(view.current);
      });
    }
    return () => {
      cancelled = true;
    };
  }, [kind]);

  return <div ref={host} className="overflow-hidden rounded-control border border-border-strong [&_.cm-editor]:max-h-[70vh] [&_.cm-editor]:min-h-[28rem]" />;
}
