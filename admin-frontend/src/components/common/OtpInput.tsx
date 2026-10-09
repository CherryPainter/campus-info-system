import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { ChangeEvent, KeyboardEvent } from "react";

interface OtpInputProps {
  value: string;
  onChange: (code: string) => void;
  length?: number;
  disabled?: boolean;
  autoFocus?: boolean;
  /** 在输入框内按下回车时触发（用于「输完直接提交」） */
  onEnter?: () => void;
}

export interface OtpInputHandle {
  /** 聚焦到输入框（如验证码校验失败后重新聚焦） */
  focus: () => void;
}

/**
 * 数字验证码输入框（默认 6 位）。
 *
 * 结构：底层一个真实 <input> 覆盖在整排展示格之上（透明），6 个格子只负责显示字符，
 * 所有输入、删除、粘贴、长按连删都交给那一个 input 承载。样式见全局 style.css 的 `.otp-*`。
 *
 * 为什么不再用「6 个真实输入框 + 自动跳格」（旧实现）：
 * 1) 退格时焦点停在当前格，当前格有值要先清掉它、再按一次才能回到上一格 —— 6 位填满时
 *    清空要点 12 次；用户反馈「验证码失效后极其反人类」正是这个。
 * 2) 每格 maxLength=1，长按退格也只删一个字符，没法连续输入。
 * 3) 每删一格都要 focus 到另一个 input，移动端浏览器会在焦点切换时重新弹出软键盘（抖屏）。
 * 单输入框天然没有这些问题：退格就是删末尾字符，长按可连续删，焦点全程不变。
 *
 * 额外收益：`autoComplete="one-time-code"` 让 iOS 支持从短信/密码管理器一键填入验证码。
 *
 * 调用方共 4 处，全部共用本组件（MFA 设置/禁用 2 处、管理端设置页 1 处、登录页两步验证 1 处）。
 */
const OtpInput = forwardRef<OtpInputHandle, OtpInputProps>(function OtpInput(
  { value, onChange, length = 6, disabled = false, autoFocus = false, onEnter },
  ref,
) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  useImperativeHandle(ref, () => ({
    focus: () => inputRef.current?.focus(),
  }), []);

  useEffect(() => {
    if (!autoFocus) return;
    const timer = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(timer);
  }, [autoFocus]);

  /** 过滤非数字并按长度截断：粘贴一整串也能正确填入 */
  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value.replace(/\D/g, "").slice(0, length));
  };

  /** 回车提交（是否允许提交由调用方判断，组件不掺业务） */
  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") onEnter?.();
  };

  /** 点格子任意位置都聚焦到那唯一的 input（它盖在上面，本身就是点击目标） */
  const focusInput = () => {
    if (!disabled) inputRef.current?.focus();
  };

  // 当前待输入格：已填满时高亮最后一格
  const activeIndex = Math.min(value.length, length - 1);

  return (
    <div
      className={`otp-input${disabled ? " is-disabled" : ""}`}
      onClick={focusInput}
    >
      {Array.from({ length }).map((_, index) => (
        <div
          key={index}
          className={`otp-cell${
            index === activeIndex && !disabled ? " is-active" : ""
          }`}
        >
          {value[index] || ""}
        </div>
      ))}
      <input
        ref={inputRef}
        className="otp-native"
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        maxLength={length}
        inputMode="numeric"
        autoComplete="one-time-code"
        aria-label="验证码"
      />
    </div>
  );
});

export default OtpInput;
