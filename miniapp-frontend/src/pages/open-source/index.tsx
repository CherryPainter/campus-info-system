import { View, Text } from '@tarojs/components';

import './index.scss';

/**
 * 开源声明
 * 列出本小程序使用到的开源软件及其许可证信息。
 */

interface OsItem {
  name: string;
  license: string;
  desc: string;
}

const LIBRARIES: OsItem[] = [
  { name: 'Taro', license: 'MIT', desc: '开放式跨端跨框架解决方案。' },
  { name: 'React', license: 'MIT', desc: '用于构建用户界面的 JavaScript 库。' },
  { name: 'NutUI React for Taro', license: 'MIT', desc: '京东风格的轻量级移动端 React 组件库。' },
  { name: 'dayjs', license: 'MIT', desc: '极简的 JavaScript 日期库。' },
  { name: 'zustand', license: 'MIT', desc: '小巧、快速且可扩展的状态管理解决方案。' },
];

export default function OpenSourcePage() {
  return (
    <View className="os-page">
      <View className="os-card">
        <Text className="os-intro">
          本小程序使用了以下开源软件，感谢开源社区的贡献。各项目的许可证信息如下：
        </Text>
        {LIBRARIES.map((lib) => (
          <View key={lib.name} className="os-item">
            <Text className="os-name">{lib.name}</Text>
            <Text className="os-license">许可证：{lib.license}</Text>
            <Text className="os-desc">{lib.desc}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}
