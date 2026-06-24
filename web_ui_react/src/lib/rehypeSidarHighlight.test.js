import { describe, expect, it } from "vitest";
import rehypeSidarHighlight from "./rehypeSidarHighlight.js";

function buildCodeTree(language, value) {
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
            properties: { className: [`language-${language}`] },
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

  it("leaves unsupported languages untouched", () => {
    const tree = buildCodeTree("ruby", "puts 'sidar'");

    rehypeSidarHighlight()(tree);

    const code = codeNode(tree);
    expect(code.properties.className).toEqual(["language-ruby"]);
    expect(code.children).toEqual([{ type: "text", value: "puts 'sidar'" }]);
  });
});
