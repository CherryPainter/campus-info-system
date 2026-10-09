import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

/**
 * 守卫：验证码输入口必须收敛到同一个 OtpInput 组件。
 *
 * 背景（2026-10-09 事故）：管理端共有 4 处 6 位验证码输入口 ——
 * 个人中心「设置 MFA」「禁用 MFA」、管理端设置页 MFA、登录页两步验证。
 * 前三处已改用单输入框实现（components/common/OtpInput.tsx），但**登录页那处漏改**，
 * 仍是「6 个真实 input + 自动跳格」的旧实现，于是用户在登录验证时仍然踩到
 * 「退格停在当前格、清空 6 位要点 12 次、长按只删一个、反复弹软键盘」。
 *
 * 本测试锁定两条不变式：
 * 1) 全站不得再出现逐格验证码输入（特征：JSX 属性 maxLength 的值为数字 1）；
 * 2) 任何出现「验证码」字样的页面/组件（OtpInput 自身除外）必须引用 OtpInput。
 *
 * 为什么用 AST 而不是正则：要精确判断「maxLength 属性的值是数字 1」，
 * 正则会把注释、字符串、maxLength={10}、maxLength={1} 的文档示例等一并误伤；
 * 项目既有约定也是源码守卫一律走 AST。
 */

const SRC_ROOT = path.resolve(__dirname, "../../..");

/** 递归收集 src 下的 ts/tsx 源码（跳过测试目录） */
function collectSources(dir: string, out: string[] = []): string[] {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) {
      if (name === "node_modules" || name === "__tests__") continue;
      collectSources(full, out);
    } else if (/\.tsx?$/.test(name)) {
      out.push(full);
    }
  }
  return out;
}

/** 单个文件的三类事实 */
interface Facts {
  rel: string;
  /** 值为数字 1 的 maxLength JSX 属性所在行号 */
  maxLengthOneLines: number[];
  /** 是否出现「验证码」字样 */
  mentionsCode: boolean;
  /** 是否 import 了 OtpInput */
  importsOtp: boolean;
}

function analyze(file: string): Facts {
  const text = fs.readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const facts: Facts = {
    rel: path.relative(SRC_ROOT, file).replace(/\\/g, "/"),
    maxLengthOneLines: [],
    mentionsCode: false,
    importsOtp: false,
  };

  const visit = (node: ts.Node) => {
    // 1) maxLength={1}
    if (
      ts.isJsxAttribute(node) &&
      node.name.getText() === "maxLength" &&
      node.initializer &&
      ts.isJsxExpression(node.initializer) &&
      node.initializer.expression &&
      ts.isNumericLiteral(node.initializer.expression) &&
      node.initializer.expression.text === "1"
    ) {
      const { line } = sf.getLineAndCharacterOfPosition(node.getStart());
      facts.maxLengthOneLines.push(line + 1);
    }
    // 2) import ... from "@/components/common/OtpInput"
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      if (node.moduleSpecifier.text.includes("OtpInput")) facts.importsOtp = true;
    }
    // 3) 「验证码」字样（字符串字面量 + JSX 文本）
    if ((ts.isStringLiteral(node) || ts.isJsxText(node)) && node.text.includes("验证码")) {
      facts.mentionsCode = true;
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return facts;
}

const FILES = collectSources(SRC_ROOT).map(analyze);

describe("验证码输入口收敛守卫", () => {
  it("不得存在逐格验证码输入（JSX maxLength={1}）", () => {
    const offenders = FILES.filter((f) => f.maxLengthOneLines.length > 0).map(
      (f) => `${f.rel}:${f.maxLengthOneLines.join(",")}`,
    );
    expect(offenders).toEqual([]);
  });

  it("出现「验证码」字样的页面/组件必须引用 OtpInput（OtpInput 自身除外）", () => {
    const offenders = FILES.filter(
      (f) => f.mentionsCode && !f.importsOtp && !f.rel.endsWith("components/common/OtpInput.tsx"),
    ).map((f) => f.rel);
    expect(offenders).toEqual([]);
  });

  it("OtpInput 组件本身存在且被实际使用（至少 3 处调用）", () => {
    const callSites = FILES.filter((f) => f.importsOtp && f.rel !== "components/common/OtpInput.tsx");
    // 个人中心 2 处 + 设置页 1 处 + 登录页 1 处 = 4 个文件中的 3 个（Profile 独占 2 处调用）
    expect(callSites.length).toBeGreaterThanOrEqual(3);
  });
});
