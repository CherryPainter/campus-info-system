/**
 * ResponsiveTable —— 响应式表格组件
 *
 * 设计目标：
 *   - 桌面端（>=768px）：完全等价于 antd 原生 <Table>，直接透传所有 props。
 *   - 移动端（<768px）：把「一行 = 一条记录、一列 = 一个字段」的表格，
 *     转换为「一张卡片 = 一条记录」的卡片列表（antd List + Card），
 *     每个字段渲染成「标签 : 值」一行，操作列的按钮同样以一行呈现，
 *     从而避免窄屏下横向滚动、信息拥挤的问题。
 *
 * 兼容性说明（覆盖本项目已有的所有用法）：
 *   - 列 columns：读取 column.title 作字段标签；有 render 时调用
 *     render(value, record, index)，否则用 dataIndex 取值。操作列（无 dataIndex）
 *     依赖 render 输出按钮，同样能正常显示。
 *   - 分页 pagination 三种形态：
 *       1) pagination={false}          —— 不分页，展示全部；
 *       2) 客户端分页（无 total）        —— 组件内部按 current/pageSize 切片；
 *       3) 服务端受控分页（有 total+onChange）—— 不切片，dataSource 即当前页数据，
 *          翻页回调透传给业务方的 onChange。
 *     controlled 的 current/pageSize 优先于内部状态。
 *   - rowKey：字符串或函数均支持。
 *   - locale.emptyText：透传给 List 的空状态。
 *   - expandable.expandedRowRender：在卡片底部展开区渲染。
 *   - loading：透传给 List。
 *
 * 用法：把页面里的 <Table ...> 直接换成 <ResponsiveTable ...> 即可，props 不变。
 */
import { useState } from 'react';
import type { ReactNode, Key } from 'react';
import { Table, List, Card, Grid, Collapse, Pagination, Spin, Empty } from 'antd';
import type { TableProps, TableColumnType, TablePaginationConfig } from 'antd';

/** 组件属性：继承 antd TableProps，额外提供移动端卡片标题 / 折叠面板自定义 */
export interface ResponsiveTableProps<T> extends TableProps<T> {
  /** 移动端每张卡片顶部的标题（可选）。桌面端忽略。 */
  mobileTitle?: (record: T, index: number) => ReactNode;
  /**
   * 移动端折叠面板模式：折叠时显示的头部（把标题与状态放在外层）。
   * 与 mobileCollapseContent 一起提供后，移动端改用 antd Collapse（点击展开详情），
   * 不再渲染卡片列表；桌面端仍为原生表格。
   */
  mobileCollapseHeader?: (record: T, index: number) => ReactNode;
  /** 移动端折叠面板模式：展开后显示的详情内容。需与 mobileCollapseHeader 搭配使用。 */
  mobileCollapseContent?: (record: T, index: number) => ReactNode;
  /** 折叠面板是否手风琴模式（一次只展开一个），默认 false。 */
  mobileCollapseAccordion?: boolean;
  /**
   * 移动端也保留原生表格（不转卡片、不转折叠面板）。
   * 适用于列很少、窄屏也能一行放下的表格：
   * 配合 column.ellipsis + tableLayout="fixed"，让放不下的内容以省略号截断。
   */
  mobileNativeTable?: boolean;
}

/**
 * 响应式表格组件
 * @template T 每行记录的数据类型
 */
export default function ResponsiveTable<T extends object = any>(
  props: ResponsiveTableProps<T>,
) {
  // 断点检测：md 对应 768px，未达到 md 视为移动端
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  // 客户端分页时的内部状态（当业务方未受控 current/pageSize 时启用）
  const [innerCurrent, setInnerCurrent] = useState(1);
  const [innerPageSize, setInnerPageSize] = useState(10);

  // 抽出移动端专属属性，其余原样透传给 antd Table
  const {
    mobileTitle,
    mobileCollapseHeader,
    mobileCollapseContent,
    mobileCollapseAccordion,
    mobileNativeTable,
    ...tableProps
  } = props;

  // ===== 桌面端，或显式要求移动端也保留原生表格 =====
  if (!isMobile || mobileNativeTable) {
    return <Table<T> {...tableProps} />;
  }

  // ===== 移动端：卡片列表 =====
  const {
    columns = [],
    dataSource = [],
    rowKey,
    loading,
    pagination: paginationProp,
    locale,
    expandable,
  } = tableProps;

  // 展平列定义（处理可能存在的分组列 children）
  const flatColumns: TableColumnType<T>[] = [];
  (columns as any[]).forEach((col) => {
    if (col && Array.isArray(col.children)) {
      flatColumns.push(...col.children);
    } else if (col) {
      flatColumns.push(col);
    }
  });

  // 分页解析
  const showPagination = paginationProp !== false;
  const pconf: TablePaginationConfig =
    paginationProp && typeof paginationProp === 'object' ? paginationProp : {};
  // 有 total 且有 onChange 视为服务端受控分页（dataSource 已是当前页数据，不能再切片）
  const serverSide = pconf.total != null && typeof pconf.onChange === 'function';

  const pageSize = pconf.pageSize ?? pconf.defaultPageSize ?? innerPageSize;
  const current = serverSide ? pconf.current ?? 1 : pconf.current ?? innerCurrent;
  const total = serverSide ? pconf.total ?? 0 : dataSource.length;

  // 客户端分页需自行切片；服务端分页直接使用全部（即当前页）数据
  const pagedData: T[] = serverSide
    ? (dataSource as T[])
    : (dataSource as T[]).slice((current - 1) * pageSize, current * pageSize);

  // 分页翻页 / 改页大小的共用处理器（List 与 Collapse 两种移动端形态复用）
  const handlePageChange = (p: number, s: number) => {
    // 未受控时更新内部状态
    if (pconf.current == null) setInnerCurrent(p);
    if (pconf.pageSize == null && s !== pageSize) setInnerPageSize(s);
    // 透传业务方回调（服务端分页据此拉取新页）
    pconf.onChange?.(p, s);
  };
  const handleSizeChange = (cur: number, s: number) => {
    if (pconf.pageSize == null) setInnerPageSize(s);
    if (pconf.current == null) setInnerCurrent(1);
    pconf.onShowSizeChange?.(cur, s);
  };

  /** 解析行的唯一 key */
  const resolveRowKey = (record: T, index: number): Key => {
    if (typeof rowKey === 'function') return rowKey(record, index);
    if (typeof rowKey === 'string') return (record as any)[rowKey] ?? index;
    return index;
  };

  // ===== 移动端：折叠面板模式（点击展开详情，头部只显示标题 + 状态） =====
  if (mobileCollapseHeader && mobileCollapseContent) {
    const items = pagedData.map((record, index) => ({
      key: String(resolveRowKey(record, index)),
      label: mobileCollapseHeader(record, index),
      children: mobileCollapseContent(record, index),
    }));
    const emptyNode: ReactNode =
      (locale?.emptyText as ReactNode) ?? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />
      );
    return (
      <Spin spinning={!!loading}>
        {items.length === 0 ? (
          <div style={{ padding: '24px 0' }}>{emptyNode}</div>
        ) : (
          <Collapse
            accordion={mobileCollapseAccordion}
            size="small"
            items={items}
            style={{ background: 'transparent' }}
          />
        )}
        {showPagination && total > pageSize && (
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <Pagination
              size="small"
              current={current}
              pageSize={pageSize}
              total={total}
              showSizeChanger={pconf.showSizeChanger}
              pageSizeOptions={pconf.pageSizeOptions as any}
              showTotal={pconf.showTotal}
              onChange={handlePageChange}
              onShowSizeChange={handleSizeChange}
            />
          </div>
        )}
      </Spin>
    );
  }

  // List 分页配置（沿用业务方的 showSizeChanger / showTotal / pageSizeOptions）
  const listPagination = showPagination
    ? {
        current,
        pageSize,
        total,
        size: 'small' as const,
        align: 'center' as const,
        showSizeChanger: pconf.showSizeChanger,
        pageSizeOptions: pconf.pageSizeOptions,
        showTotal: pconf.showTotal,
        onChange: handlePageChange,
        onShowSizeChange: handleSizeChange,
      }
    : (false as const);


  return (
    <List<T>
      loading={loading}
      split={false}
      dataSource={pagedData}
      rowKey={rowKey as any}
      locale={locale ? { emptyText: locale.emptyText as ReactNode } : undefined}
      pagination={listPagination}
      renderItem={(record, index) => {
        const key = resolveRowKey(record, index);
        return (
          <List.Item
            key={key}
            style={{ padding: 0, border: 'none', display: 'block' }}
          >
            <Card
              size="small"
              style={{ marginBottom: 12, borderRadius: 8 }}
              styles={{ body: { padding: 12 } }}
            >
              {/* 可选：卡片标题 */}
              {mobileTitle && (
                <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 15 }}>
                  {mobileTitle(record, index)}
                </div>
              )}

              {/* 逐字段渲染为「标签 : 值」一行 */}
              {flatColumns.map((col, ci) => {
                const dataIndex = (col as any).dataIndex;
                // 依据 dataIndex 取原始值（支持数组路径）
                const rawValue =
                  dataIndex == null
                    ? undefined
                    : Array.isArray(dataIndex)
                      ? dataIndex.reduce(
                          (acc: any, k: any) => (acc == null ? acc : acc[k]),
                          record as any,
                        )
                      : (record as any)[dataIndex];
                // 有 render 用 render 的结果，否则用原始值
                const content = (
                  col.render ? col.render(rawValue, record, index) : rawValue
                ) as ReactNode;
                // 字段标签（title 可能是函数）
                const label =
                  typeof col.title === 'function'
                    ? (col.title as any)({})
                    : col.title;
                // 空值占位
                const displayContent =
                  content === null || content === undefined || content === ''
                    ? '-'
                    : content;
                const colKey = (col.key ??
                  (Array.isArray(dataIndex)
                    ? dataIndex.join('.')
                    : dataIndex) ??
                  ci) as Key;
                return (
                  <div
                    key={colKey}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'flex-start',
                      gap: 12,
                      padding: '6px 0',
                      borderBottom:
                        ci < flatColumns.length - 1
                          ? '1px solid #f5f5f5'
                          : 'none',
                    }}
                  >
                    <span
                      style={{
                        color: '#8c8c8c',
                        flexShrink: 0,
                        fontSize: 13,
                        lineHeight: '22px',
                      }}
                    >
                      {label}
                    </span>
                    <span
                      style={{
                        textAlign: 'right',
                        wordBreak: 'break-word',
                        minWidth: 0,
                      }}
                    >
                      {displayContent}
                    </span>
                  </div>
                );
              })}

              {/* 可展开行：在卡片底部渲染详情 */}
              {expandable?.expandedRowRender && (
                <div
                  style={{
                    marginTop: 8,
                    paddingTop: 8,
                    borderTop: '1px dashed #f0f0f0',
                  }}
                >
                  {expandable.expandedRowRender(record, index, 0, true)}
                </div>
              )}
            </Card>
          </List.Item>
        );
      }}
    />
  );
}
