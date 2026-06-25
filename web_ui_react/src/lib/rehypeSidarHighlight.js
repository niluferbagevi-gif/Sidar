import bash from "highlight.js/lib/languages/bash";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import { createLowlight } from "lowlight";

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

const lowlight = createLowlight(SIDAR_LANGUAGES);
lowlight.registerAlias(SIDAR_LANGUAGE_ALIASES);

function getText(node) {
  if (!node) {
    return "";
  }
  if (node.type === "text") {
    return node.value || "";
  }
  return Array.isArray(node.children) ? node.children.map(getText).join("") : "";
}

function getClassNames(node) {
  return Array.isArray(node?.properties?.className)
    ? node.properties.className
    : [];
}

function getLanguage(node) {
  const classNames = getClassNames(node);
  const languageClass = classNames.find(
    (className) => className.startsWith("language-") || className.startsWith("lang-"),
  );
  if (!languageClass) {
    return "";
  }
  return languageClass.replace(/^(language|lang)-/, "").toLowerCase();
}

function visitCodeBlocks(node, parent) {
  if (!node || typeof node !== "object") {
    return;
  }

  if (node.type === "element" && node.tagName === "code" && parent?.tagName === "pre") {
    const language = getLanguage(node);
    if (!language || !lowlight.registered(language)) {
      return;
    }

    const highlighted = lowlight.highlight(language, getText(node));
    const className = new Set([...getClassNames(node), "hljs"]);
    node.properties = { ...node.properties, className: Array.from(className) };
    node.children = highlighted.children;
    return;
  }

  if (Array.isArray(node.children)) {
    for (const child of node.children) {
      visitCodeBlocks(child, node);
    }
  }
}

export default function rehypeSidarHighlight() {
  return function transform(tree) {
    visitCodeBlocks(tree, undefined);
  };
}
