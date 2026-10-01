import { useState, useCallback } from 'react';
import { View, Text, Input, Textarea } from '@tarojs/components';
import Taro, { useLoad } from '@tarojs/taro';

import * as webhookApi from '@/api/webhook';
import { STUDENT_WEBHOOK_MODULES, type ThirdPartyWebhook } from '@/api/webhook';
import Switch from '@/components/Switch';
import './index.scss';

interface FormState {
  id: number | null;
  name: string;
  url: string;
  modules: string[];
  description: string;
  is_enabled: boolean;
}

const EMPTY_FORM: FormState = {
  id: null,
  name: '',
  url: '',
  modules: ['course'],
  description: '',
  is_enabled: true,
};

const MODULE_LABEL: Record<string, string> = {
  course: '课表',
  electricity: '电量',
  weather: '天气',
};

/**
 * 第三方消息通知（学生自建 webhook）
 *
 * 学生可在此自助添加企业微信机器人 webhook，仅限个人相关模块（课表 / 电量 / 天气），
 * 服务端强制 scope=student + 仅本人。列表仅展示本人创建的 webhook，免审核即生效。
 *
 * UI：与「设置」页保持一致的分组卡片风格，近白底 + 白卡 + 行内细线分隔，
 * 开关使用项目自绘 Switch，避免 NutUI 样式未进产物导致裸节点。
 */
export default function ThirdPartyNotifyPage() {
  const [list, setList] = useState<ThirdPartyWebhook[]>([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ThirdPartyWebhook | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await webhookApi.listMine();
      if (res.status === 'success' && res.data) {
        setList(res.data);
      }
    } catch {
      // 未绑定/未登录等由请求层统一处理，这里静默即可
    } finally {
      setLoading(false);
    }
  }, []);

  useLoad(() => {
    fetchList();
  });

  const openAdd = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setShowForm(true);
  };

  const openEdit = (item: ThirdPartyWebhook) => {
    setEditing(item);
    setForm({
      id: item.id,
      name: item.name,
      url: item.url,
      modules: item.module_list && item.module_list.length ? item.module_list : ['course'],
      description: item.description || '',
      is_enabled: item.is_enabled,
    });
    setShowForm(true);
  };

  const closeForm = () => {
    setShowForm(false);
    setEditing(null);
  };

  const toggleModule = (value: string) => {
    setForm((prev) => {
      const has = prev.modules.includes(value);
      const next = has
        ? prev.modules.filter((m) => m !== value)
        : [...prev.modules, value];
      return { ...prev, modules: next.length ? next : ['course'] };
    });
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      Taro.showToast({ title: '请填写名称', icon: 'none' });
      return;
    }
    if (!form.url.trim()) {
      Taro.showToast({ title: '请填写 Webhook URL', icon: 'none' });
      return;
    }
    if (!/^https:\/\//.test(form.url.trim())) {
      Taro.showToast({ title: 'URL 须以 https:// 开头', icon: 'none' });
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        url: form.url.trim(),
        modules: form.modules,
        description: form.description.trim(),
        is_enabled: form.is_enabled,
      };
      const res = editing
        ? await webhookApi.updateWebhook(editing.id, payload)
        : await webhookApi.createWebhook(payload);
      if (res.status === 'success') {
        Taro.showToast({ title: editing ? '已保存' : '已添加', icon: 'success' });
        closeForm();
        fetchList();
      } else {
        Taro.showToast({ title: res.message || '保存失败', icon: 'none' });
      }
    } catch {
      Taro.showToast({ title: '保存失败', icon: 'none' });
    } finally {
      setSaving(false);
    }
  };

  const handleToggleEnabled = async (item: ThirdPartyWebhook) => {
    try {
      const res = await webhookApi.updateWebhook(item.id, { is_enabled: !item.is_enabled });
      if (res.status === 'success') {
        fetchList();
      }
    } catch {
      Taro.showToast({ title: '操作失败', icon: 'none' });
    }
  };

  const handleTest = async (item: ThirdPartyWebhook) => {
    setTestingId(item.id);
    try {
      const res = await webhookApi.testWebhook(item.id);
      if (res.status === 'success') {
        Taro.showToast({ title: '测试消息已发送', icon: 'success' });
      } else {
        Taro.showToast({ title: res.message || '测试失败', icon: 'none' });
      }
    } catch {
      Taro.showToast({ title: '测试失败', icon: 'none' });
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = (item: ThirdPartyWebhook) => {
    Taro.showModal({
      title: '删除确认',
      content: `确定删除「${item.name}」？删除后该 webhook 不再接收推送。`,
      confirmText: '删除',
      confirmColor: '#e8380f',
      success: async (r) => {
        if (!r.confirm) return;
        try {
          const res = await webhookApi.deleteWebhook(item.id);
          if (res.status === 'success') {
            Taro.showToast({ title: '已删除', icon: 'success' });
            fetchList();
          }
        } catch {
          Taro.showToast({ title: '删除失败', icon: 'none' });
        }
      },
    });
  };

  const renderList = () => {
    if (loading && !showForm) {
      return (
        <View className="tpn-card tpn-empty">
          <Text className="tpn-empty-text">加载中…</Text>
        </View>
      );
    }

    if (list.length === 0) {
      return (
        <View className="tpn-card tpn-empty">
          <Text className="tpn-empty-text">还没有配置任何通知</Text>
        </View>
      );
    }

    return (
      <>
        {list.map((item) => (
          <View className="tpn-card tpn-group" key={item.id}>
            <View className="tpn-cell tpn-cell-switch">
              <Text className="tpn-cell-label tpn-cell-label-strong">{item.name}</Text>
              <Switch
                checked={item.is_enabled}
                onChange={() => handleToggleEnabled(item)}
              />
            </View>
            <View className="tpn-cell">
              <Text className="tpn-cell-url" numberOfLines={1}>
                {item.url}
              </Text>
            </View>
            <View className="tpn-cell">
              <View className="tpn-tags">
                {(item.module_list && item.module_list.length
                  ? item.module_list
                  : []
                ).map((m) => (
                  <Text className="tpn-tag" key={m}>
                    {MODULE_LABEL[m] || m}
                  </Text>
                ))}
              </View>
            </View>
            <View className="tpn-cell tpn-cell-actions">
              <View
                className="tpn-action"
                onClick={() => handleTest(item)}
              >
                <Text className="tpn-action-text">
                  {testingId === item.id ? '测试中…' : '测试'}
                </Text>
              </View>
              <View className="tpn-action" onClick={() => openEdit(item)}>
                <Text className="tpn-action-text">编辑</Text>
              </View>
              <View className="tpn-action tpn-action-danger" onClick={() => handleDelete(item)}>
                <Text className="tpn-action-text">删除</Text>
              </View>
            </View>
          </View>
        ))}
      </>
    );
  };

  const renderForm = () => (
    <>
      <View className="tpn-card tpn-group">
        <View className="tpn-cell tpn-cell-input">
          <Text className="tpn-cell-label">名称</Text>
          <Input
            className="tpn-input"
            value={form.name}
            placeholder="如：我的课表通知"
            placeholderClass="tpn-placeholder"
            onInput={(e: any) => setForm((p) => ({ ...p, name: e.detail.value }))}
          />
        </View>
        <View className="tpn-cell tpn-cell-textarea">
          <Text className="tpn-cell-label">Webhook URL</Text>
          <Textarea
            className="tpn-textarea"
            value={form.url}
            placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
            placeholderClass="tpn-placeholder"
            onInput={(e: any) => setForm((p) => ({ ...p, url: e.detail.value }))}
          />
        </View>
        <View className="tpn-cell tpn-cell-input">
          <Text className="tpn-cell-label">描述（可选）</Text>
          <Input
            className="tpn-input"
            value={form.description}
            placeholder="选填，便于自己识别"
            placeholderClass="tpn-placeholder"
            onInput={(e: any) => setForm((p) => ({ ...p, description: e.detail.value }))}
          />
        </View>
      </View>

      <Text className="tpn-card-title">接收模块</Text>
      <View className="tpn-card tpn-group">
        <View className="tpn-cell tpn-cell-chips">
          <View className="tpn-chips">
            {STUDENT_WEBHOOK_MODULES.map((m) => {
              const active = form.modules.includes(m.value);
              return (
                <View
                  key={m.value}
                  className={`tpn-chip ${active ? 'tpn-chip-active' : ''}`}
                  onClick={() => toggleModule(m.value)}
                >
                  <Text className="tpn-chip-text">{m.label}</Text>
                </View>
              );
            })}
          </View>
        </View>
      </View>

      <View className="tpn-card tpn-group">
        <View className="tpn-cell tpn-cell-switch">
          <Text className="tpn-cell-label">启用</Text>
          <Switch
            checked={form.is_enabled}
            onChange={(value) => setForm((p) => ({ ...p, is_enabled: value }))}
          />
        </View>
      </View>

      <View className="tpn-actionbar">
        <View
          className={`tpn-btn tpn-btn-ghost${saving ? ' tpn-btn-disabled' : ''}`}
          onClick={closeForm}
        >
          <Text className="tpn-btn-text-ghost">取消</Text>
        </View>
        <View
          className={`tpn-btn tpn-btn-primary${saving ? ' tpn-btn-disabled' : ''}`}
          onClick={handleSave}
        >
          <Text className="tpn-btn-text-primary">{saving ? '保存中…' : '保存'}</Text>
        </View>
      </View>
    </>
  );

  return (
    <View className="tpn-page">
      <View className="tpn-card tpn-intro">
        <Text className="tpn-intro-text">
          自助添加企业微信机器人 Webhook，仅接收与你个人相关的推送（课表 / 电量 / 天气）。
          配置即时生效，无需审核；仅本人可见与管理，接收范围固定为「仅自己」。
        </Text>
      </View>

      {showForm ? renderForm() : renderList()}

      {!showForm && (
        <View
          className="tpn-btn tpn-btn-primary tpn-btn-block"
          onClick={openAdd}
        >
          <Text className="tpn-btn-text-primary">添加通知</Text>
        </View>
      )}

      {!showForm && (
        <Text className="tpn-foot">
          提示：课表与天气为全量广播副本；电量按你本人数据定向。
        </Text>
      )}
    </View>
  );
}
