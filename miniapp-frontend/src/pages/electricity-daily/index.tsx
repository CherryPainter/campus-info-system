import { ScrollView } from '@tarojs/components';
import Taro, { useLoad, useRouter } from '@tarojs/taro';

import ElectricityDailyDetail from '@/components/ElectricityDailyDetail';
import './index.scss';

/**
 * 用电详情（某一个用电日）
 *
 * 正文全部由 <ElectricityDailyDetail> 渲染 —— 与站内信「电量日报」点进来看到的
 * 是同一份实现、同一副面孔，避免同一份数据两处渲染长出两套视觉。
 * 本页只负责取路由参数、设置标题栏、提供页面底色。
 *
 * 路由参数：date（用电日，YYYY-MM-DD）
 */
export default function ElectricityDailyPage() {
  const router = useRouter();
  const date = String(router.params?.date || '').trim();

  useLoad(() => {
    Taro.setNavigationBarTitle({ title: '用电详情' });
  });

  return (
    <ScrollView scrollY className="elecd-page">
      <ElectricityDailyDetail date={date} />
    </ScrollView>
  );
}
