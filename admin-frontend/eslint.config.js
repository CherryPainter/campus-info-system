// ESLint 配置（flat config，ESM）
// 渐进式：当前以"低风险高价值"规则为主，warning 不阻塞 CI，error 才红。
// 随团队习惯成熟，再逐步收窄规则（如开启 no-explicit-any 为 warn）。
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

export default [
  {
    ignores: ['dist', 'node_modules', 'build', '*.config.js', '*.config.ts'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
    },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        window: 'readonly',
        document: 'readonly',
        console: 'readonly',
        process: 'readonly',
        module: 'writable',
        require: 'readonly',
        setTimeout: 'readonly',
        setInterval: 'readonly',
        clearTimeout: 'readonly',
        clearInterval: 'readonly',
        fetch: 'readonly',
        localStorage: 'readonly',
        location: 'readonly',
        history: 'readonly',
        navigator: 'readonly',
      },
    },
    rules: {
      // React Hooks 规则：rules-of-hooks 是 error（抓破坏 hooks 调用顺序的真 bug），
      // exhaustive-deps 是 warn（依赖遗漏提示，不阻塞）
      ...reactHooks.configs.recommended.rules,
      // antd / React19 项目中 any 较常见，先放行，后续逐步治理
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/ban-types': 'off',
      '@typescript-eslint/no-empty-interface': 'off',
      '@typescript-eslint/no-namespace': 'off',
      '@typescript-eslint/no-empty-object-type': 'off',
      'no-empty': 'off',
      // 未使用变量先给 warning（不阻塞），并允许下划线前缀占位
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      'no-unused-vars': 'off',
    },
  },
];
