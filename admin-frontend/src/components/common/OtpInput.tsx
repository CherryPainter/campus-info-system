import { useEffect, useRef } from "react";
import { Input, type InputRef } from "antd";
import type { ClipboardEvent, KeyboardEvent } from "react";

interface OtpInputProps {
  value: string;
  onChange: (code: string) => void;
  length?: number;
  disabled?: boolean;
  autoFocus?: boolean;
}

/**
 * 数字验证码输入框（默认 6 位）。
 *
 * 统一管理各格子的 ref、自动跳格、退格回退与粘贴填充，
 * 避免在多个使用点重复实现相同逻辑（此前 Profile 的启用/禁用弹窗各写了一份几乎相同的实现）。
 */
export default function OtpInput({
  value,
  onChange,
  length = 6,
  disabled = false,
  autoFocus = false,
}: OtpInputProps) {
  const refs = useRef<(InputRef | null)[]>([]);

  useEffect(() => {
    if (!autoFocus) return;
    const timer = setTimeout(() => refs.current[0]?.focus(), 50);
    return () => clearTimeout(timer);
  }, [autoFocus]);

  const focusAt = (index: number) => {
    if (index >= 0 && index < length) {
      refs.current[index]?.focus();
    }
  };

  const handleChange = (index: number, raw: string) => {
    const digit = raw.replace(/\D/g, "").slice(-1);
    const chars = value.split("");
    if (digit) {
      chars[index] = digit;
      onChange(chars.join("").slice(0, length));
      focusAt(index + 1);
    } else {
      chars[index] = "";
      onChange(chars.join("").slice(0, length));
    }
  };

  const handleKeyDown = (index: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace") {
      if (!value[index] && index > 0) {
        focusAt(index - 1);
      }
    } else if (e.key === "ArrowLeft" && index > 0) {
      focusAt(index - 1);
    } else if (e.key === "ArrowRight" && index < length - 1) {
      focusAt(index + 1);
    }
  };

  const handlePaste = (e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, length);
    if (pasted) {
      onChange(pasted);
      focusAt(Math.min(pasted.length, length - 1));
    }
  };

  return (
    <div style={{ display: "flex", justifyContent: "center", gap: 8 }}>
      {Array.from({ length }).map((_, index) => (
        <Input
          key={index}
          ref={(el) => {
            refs.current[index] = el;
          }}
          value={value[index] || ""}
          onChange={(e) => handleChange(index, e.target.value)}
          onKeyDown={(e) => handleKeyDown(index, e)}
          onPaste={handlePaste}
          maxLength={1}
          size="large"
          disabled={disabled}
          inputMode="numeric"
          style={{
            width: 44,
            height: 48,
            textAlign: "center",
            fontSize: 20,
            fontWeight: 500,
            borderRadius: 4,
          }}
        />
      ))}
    </div>
  );
}
