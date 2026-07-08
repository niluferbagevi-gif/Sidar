import { describe, expect, it } from "vitest";
import rehypeSidarHighlight, {
  __rehypeSidarHighlightTestHooks,
} from "./rehypeSidarHighlight.js";

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

  it("highlights language-prefixed javascript aliases", () => {
    const tree = buildCodeTree("js", "const sidar = true;");

    rehypeSidarHighlight()(tree);

    const code = codeNode(tree);
    expect(code.properties.className).toEqual(["language-js", "hljs"]);
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

  it("accepts undefined trees as a no-op transform", () => {
    expect(() => rehypeSidarHighlight()(undefined)).not.toThrow();
  });

  it("parses nested highlighted span html into nested HAST children", () => {
    const children = __rehypeSidarHighlightTestHooks.highlightHtmlToHastChildren(
      '</span><span class="hljs-string">f&quot;<span class="hljs-subst">{value}</span>&#x27;&#39;</span>&amp;',
    );

    expect(children).toEqual([
      {
        type: "element",
        tagName: "span",
        properties: { className: ["hljs-string"] },
        children: [
          { type: "text", value: "f\"" },
          {
            type: "element",
            tagName: "span",
            properties: { className: ["hljs-subst"] },
            children: [{ type: "text", value: "{value}" }],
          },
          { type: "text", value: "''" },
        ],
      },
      { type: "text", value: "&" },
    ]);
  });

  it("drops extra whitespace while parsing highlighted span class names", () => {
    const children = __rehypeSidarHighlightTestHooks.highlightHtmlToHastChildren(
      '<span class=" hljs-string  custom ">sidar</span>',
    );

    expect(children).toEqual([
      {
        type: "element",
        tagName: "span",
        properties: { className: ["hljs-string", "custom"] },
        children: [{ type: "text", value: "sidar" }],
      },
    ]);
  });

  it("returns no highlighted children for empty or undefined html", () => {
    expect(__rehypeSidarHighlightTestHooks.highlightHtmlToHastChildren()).toEqual([]);
    expect(__rehypeSidarHighlightTestHooks.highlightHtmlToHastChildren("")).toEqual([]);
  });

  it("decodes supported html entities and treats missing values as empty text", () => {
    expect(
      __rehypeSidarHighlightTestHooks.decodeHtmlText("&lt;&gt;&quot;&#x27;&#39;&amp;"),
    ).toBe("<>\"''&");
    expect(__rehypeSidarHighlightTestHooks.decodeHtmlText()).toBe("");
  });

  it("decodes highlighted html entities back into HAST text nodes", () => {
    const tree = buildCodeTree("javascript", "if (a < b && c > d) console.log(\"sidar\");");

    rehypeSidarHighlight()(tree);

    const flattenedText = codeNode(tree)
      .children.flatMap((child) => child.children || [child])
      .filter((child) => child.type === "text")
      .map((child) => child.value)
      .join("");
    expect(flattenedText).toContain("<");
    expect(flattenedText).toContain("&&");
    expect(flattenedText).toContain(">");
    expect(flattenedText).toContain("\"sidar\"");
  });

  it("parses spans without class attributes as classless HAST elements", () => {
    expect(__rehypeSidarHighlightTestHooks.classNamesFromHtml("<span>sidar</span>")).toEqual([]);

    const children = __rehypeSidarHighlightTestHooks.highlightHtmlToHastChildren(
      "<span>plain</span>",
    );

    expect(children).toEqual([
      {
        type: "element",
        tagName: "span",
        properties: { className: [] },
        children: [{ type: "text", value: "plain" }],
      },
    ]);
  });

  it("keeps text inside malformed open highlighted spans", () => {
    const children = __rehypeSidarHighlightTestHooks.highlightHtmlToHastChildren(
      '<span class="hljs-keyword">const',
    );

    expect(children).toEqual([
      {
        type: "element",
        tagName: "span",
        properties: { className: ["hljs-keyword"] },
        children: [{ type: "text", value: "const" }],
      },
    ]);
  });

  it("allows the module to be imported again without alias registration errors", async () => {
    await expect(import("./rehypeSidarHighlight.js?duplicate-alias-test")).resolves.toBeTruthy();
  });

});
