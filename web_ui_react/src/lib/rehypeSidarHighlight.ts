import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";

const SIDAR_LANGUAGES = {
  bash,
  javascript,
  json,
  python,
};

const SIDAR_LANGUAGE_ALIASES = {
  bash: ["sh", "shell", "zsh"],
  javascript: ["js", "jsx", "node"],
  python: ["py"],
};

interface HastElement {
  type: "element";
  tagName: string;
  properties?: Record<string, unknown>;
  children: unknown[];
}

interface HastRoot {
  type?: "root";
  children: unknown[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isElement(node: unknown): node is HastElement {
  return isRecord(node) && node.type === "element" && typeof node.tagName === "string" && Array.isArray(node.children);
}

for (const [language, definition] of Object.entries(SIDAR_LANGUAGES)) {
  if (!hljs.getLanguage(language)) {
    hljs.registerLanguage(language, definition);
  }
}

for (const [languageName, aliases] of Object.entries(SIDAR_LANGUAGE_ALIASES)) {
  hljs.registerAliases(aliases, { languageName });
}

function getText(node: unknown): string {
  if (!isRecord(node)) {
    return "";
  }
  if (node.type === "text" && typeof node.value === "string") {
    return node.value;
  }
  return Array.isArray(node.children) ? node.children.map(getText).join("") : "";
}

function getClassNames(node: HastElement): string[] {
  const className = node.properties?.className;
  return Array.isArray(className)
    ? className.filter((value): value is string => typeof value === "string")
    : [];
}

function getLanguage(node: HastElement): string {
  const classNames = getClassNames(node);
  const languageClass = classNames.find(
    (className) => className.startsWith("language-") || className.startsWith("lang-"),
  );
  if (!languageClass) {
    return "";
  }
  return languageClass.replace(/^(language|lang)-/, "").toLowerCase();
}

function decodeHtmlText(value: unknown): string {
  return String(value || "")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

function classNamesFromHtml(value: unknown): string[] {
  const match = String(value || "").match(/class="([^"]+)"/);
  return match?.[1]?.split(/\s+/).filter(Boolean) || [];
}

function highlightHtmlToHastChildren(html: unknown): unknown[] {
  const root: HastRoot = { type: "root", children: [] };
  const stack: Array<HastRoot | HastElement> = [root];
  const tokenPattern = /<span(?:\s+class="[^"]+")?>|<\/span>|[^<]+/g;
  for (const token of String(html || "").match(tokenPattern) || []) {
    const current = stack[stack.length - 1];
    if (token.startsWith("<span")) {
      const node: HastElement = {
        type: "element",
        tagName: "span",
        properties: { className: classNamesFromHtml(token) },
        children: [],
      };
      current.children.push(node);
      stack.push(node);
      continue;
    }
    if (token === "</span>") {
      if (stack.length > 1) {
        stack.pop();
      }
      continue;
    }
    current.children.push({ type: "text", value: decodeHtmlText(token) });
  }
  return root.children;
}

function visitCodeBlocks(node: unknown, parent?: HastElement): void {
  if (!isRecord(node)) return;
  if (isElement(node) && node.tagName === "code" && parent?.tagName === "pre") {
    const language = getLanguage(node);
    if (!language || !hljs.getLanguage(language)) {
      return;
    }

    const highlighted = hljs.highlight(getText(node), { language, ignoreIllegals: true });
    const className = new Set([...getClassNames(node), "hljs"]);
    node.properties = { ...node.properties, className: Array.from(className) };
    node.children = highlightHtmlToHastChildren(highlighted.value);
    return;
  }

  if (Array.isArray(node.children)) {
    for (const child of node.children) visitCodeBlocks(child, isElement(node) ? node : parent);
  }
}

export default function rehypeSidarHighlight() {
  return function transform(tree: unknown): void {
    visitCodeBlocks(tree, undefined);
  };
}

export const __rehypeSidarHighlightTestHooks = {
  classNamesFromHtml,
  decodeHtmlText,
  highlightHtmlToHastChildren,
  visitCodeBlocks,
};
