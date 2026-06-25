import { describe, expect, it } from "vitest";
import rehypeSidarHighlight from "./rehypeSidarHighlight.js";

function buildCodeTree(language, value, classPrefix = "language") {
  const className = language ? [`${classPrefix}-${language}`] : [];
  return {
    type: "root",
    children: [
      {
        type: "element",
        tagName: "pre",
        properties: {},
        children: [
          {
            type: "element",
            tagName: "code",
            properties: { className },
            children: [{ type: "text", value }],
          },
        ],
      },
    ],
  };
}

function codeNode(tree) {
  return tree.children[0].children[0];
}

describe("rehypeSidarHighlight", () => {
  it("highlights registered chat languages without loading the common bundle", () => {
    const tree = buildCodeTree("bash", "echo sidar");

    rehypeSidarHighlight()(tree);

    const code = codeNode(tree);
    expect(code.properties.className).toContain("hljs");
    expect(code.children.some((child) => child.type === "element")).toBe(true);
  });

  it("highlights aliased lang-prefixed code blocks", () => {
    const tree = buildCodeTree("py", "print('sidar')", "lang");

    rehypeSidarHighlight()(tree);

    const code = codeNode(tree);
    expect(code.properties.className).toEqual(["lang-py", "hljs"]);
    expect(code.children.some((child) => child.type === "element")).toBe(true);
  });

  it("leaves unsupported languages untouched", () => {
    const tree = buildCodeTree("ruby", "puts 'sidar'");

    rehypeSidarHighlight()(tree);

    const code = codeNode(tree);
    expect(code.properties.className).toEqual(["language-ruby"]);
    expect(code.children).toEqual([{ type: "text", value: "puts 'sidar'" }]);
  });

  it("leaves code blocks without a language untouched", () => {
    const tree = buildCodeTree("", "plain sidar");

    rehypeSidarHighlight()(tree);

    const code = codeNode(tree);
    expect(code.properties.className).toEqual([]);
    expect(code.children).toEqual([{ type: "text", value: "plain sidar" }]);
  });

  it("extracts nested text before highlighting", () => {
    const tree = buildCodeTree("javascript", "");
    codeNode(tree).children = [
      { type: "text", value: "const " },
      { type: "element", tagName: "span", children: [{ type: "text", value: "answer = 42;" }] },
    ];

    rehypeSidarHighlight()(tree);

    const code = codeNode(tree);
    expect(code.properties.className).toContain("hljs");
    expect(code.children.some((child) => child.type === "element")).toBe(true);
  });

  it("treats missing and null text children as empty strings", () => {
    const tree = buildCodeTree("json", "");
    codeNode(tree).children = [{ type: "text" }, null];

    rehypeSidarHighlight()(tree);

    const code = codeNode(tree);
    expect(code.properties.className).toContain("hljs");
    expect(code.children).toEqual([]);
  });

  it("treats nested non-text nodes without children as empty strings", () => {
    const tree = buildCodeTree("json", "");
    codeNode(tree).children = [{ type: "element", tagName: "span" }];

    rehypeSidarHighlight()(tree);

    const code = codeNode(tree);
    expect(code.properties.className).toContain("hljs");
    expect(code.children).toEqual([]);
  });

  it("ignores code nodes with malformed className properties", () => {
    const tree = buildCodeTree("python", "print('sidar')");
    const code = codeNode(tree);
    code.properties.className = "language-python";

    rehypeSidarHighlight()(tree);

    expect(code.properties.className).toBe("language-python");
    expect(code.children).toEqual([{ type: "text", value: "print('sidar')" }]);
  });

  it("ignores class names without a language marker", () => {
    const tree = buildCodeTree("python", "print('sidar')");
    const code = codeNode(tree);
    code.properties.className = ["chat-code"];

    rehypeSidarHighlight()(tree);

    expect(code.properties.className).toEqual(["chat-code"]);
    expect(code.children).toEqual([{ type: "text", value: "print('sidar')" }]);
  });

  it("ignores malformed or non-code AST branches", () => {
    const tree = {
      type: "root",
      children: [null, "sidar", { type: "element", tagName: "code", children: null }],
    };

    expect(() => rehypeSidarHighlight()(tree)).not.toThrow();
    expect(tree.children[2].children).toBeNull();
  });
});
