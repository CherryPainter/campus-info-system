#!/usr/bin/env python3
"""
将处理后的课程CSV文件转换为图片
"""

import os
import sys
import warnings
from datetime import datetime

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image

# 关闭所有警告
warnings.filterwarnings("ignore")

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 导入配置和日志模块
from config import CONFIG
from logger import get_logger


class CsvToImage:
    def __init__(self, csv_file):
        """
        初始化CSV转图片转换器

        Args:
            csv_file (str): CSV文件路径
        """
        # 初始化日志记录器
        self.logger = get_logger("image")

        self.csv_file = csv_file
        self.df = None

        # 从配置中获取输出目录
        output_dir = CONFIG["image"]["output_dir"]

        # 确保输出目录存在
        abs_output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", output_dir))
        os.makedirs(abs_output_dir, exist_ok=True)
        self.abs_output_dir = abs_output_dir

        self.logger.info(f"CsvToImage初始化完成，CSV文件: {csv_file}")

    def load_csv(self):
        """
        加载CSV文件
        """
        try:
            # 读取CSV文件
            self.df = pd.read_csv(self.csv_file)
            self.logger.info(f"成功加载CSV文件: {self.csv_file}")
            self.logger.info(f"数据行数: {len(self.df)}")
            return True
        except Exception as e:
            self.logger.error(f"加载CSV文件失败: {e}")
            return False

    def _backup_file(self, file_path):
        """
        备份文件到历史目录

        Args:
            file_path (str): 要备份的文件路径
        """
        if os.path.exists(file_path):
            # 确定文件类型（images或processed）
            file_dir = os.path.dirname(file_path)
            if "images" in file_dir:
                file_type = "images"
            elif "processed" in file_dir:
                file_type = "processed"
            else:
                file_type = "other"

            # 从配置中获取历史目录
            processing_config = CONFIG["processing"]
            history_dir = processing_config["history_dir"]

            # 创建历史目录结构，按时间戳归档
            base_history_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", history_dir)
            )
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            history_dir = os.path.join(base_history_dir, file_type, timestamp)
            os.makedirs(history_dir, exist_ok=True)

            # 生成备份文件名
            file_name = os.path.basename(file_path)
            backup_file_path = os.path.join(history_dir, file_name)

            # 移动文件到历史目录
            try:
                os.rename(file_path, backup_file_path)
                self.logger.info(f"历史文件已备份到: {backup_file_path}")
            except Exception as e:
                self.logger.error(f"备份文件失败: {e}")

    def _backup_all_old_images(self, output_dir, new_filename):
        """
        备份目录中所有旧图片到历史目录

        Args:
            output_dir (str): 图片输出目录
            new_filename (str): 新生成的图片文件名
        """
        # 确保目录存在
        if not os.path.exists(output_dir):
            self.logger.debug(f"输出目录不存在，跳过备份: {output_dir}")
            return

        # 遍历目录中的所有文件
        try:
            for file_name in os.listdir(output_dir):
                # 只处理图片文件
                if file_name.endswith(".png"):
                    file_path = os.path.join(output_dir, file_name)
                    self._backup_file(file_path)
        except Exception as e:
            self.logger.error(f"遍历备份文件时出错: {e}")

    def generate_image(self, filename=None):
        """
        生成图片

        Args:
            filename (str): 输出文件名

        Returns:
            str: 生成的图片路径
        """
        if self.df is None:
            self.logger.error("请先加载CSV文件")
            return None

        # 获取配置
        image_config = CONFIG["image"]
        class_name = CONFIG["class_name"]

        # 设置中文字体：复用 app.utils.chinese_font 的健壮解析策略，
        # 在选用字体前实测 freetype 是否可加载，避免渲染时
        # "Can not load face (unknown file format)" 导致整张图生成失败。
        # 延迟导入，保证独立运行（project_root 尚未加入 sys.path）时不报错。
        try:
            from app.utils.chinese_font import setup_chinese_font

            self.chinese_font = setup_chinese_font()
        except Exception as e:
            self.logger.error(f"设置中文字体失败，回退默认字体: {e}")
            plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["axes.unicode_minus"] = False
            self.chinese_font = fm.FontProperties(family="DejaVu Sans")

        # 空数据保护：尚未排课（如选择了还没排课的下学期）时数据为空，
        # 直接生成空白占位图，避免 matplotlib 渲染空表格触发 IndexError（cellText[0] 越界）
        # 否则会让整个爬取子进程返回非 0，导致预约爬取任务被误判为失败。
        if len(self.df) == 0:
            self.logger.warning("课程数据为空（可能尚未排课），生成空白占位图")
            return self._generate_empty_placeholder(filename)

        # 计算合适的图片大小
        num_rows = len(self.df) + 1  # 加上表头
        fig_width = 10  # 保持宽度
        fig_height = max(3, num_rows * 0.4)  # 进一步减小高度，使图片更紧凑
        # 创建图形
        fig, ax = plt.subplots(figsize=(fig_width, fig_height))

        # 加载用户提供的背景图片（循环平铺）
        try:
            # 从配置中获取是否启用背景图片
            enable_background = image_config.get("enable_background", True)

            if enable_background:
                # 使用绝对路径加载背景图片
                background_path = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "..", "static", "background.png")
                )
                self.logger.info(f"尝试加载背景图片: {background_path}")

                if os.path.exists(background_path):
                    # 读取背景图片
                    bg_img = Image.open(background_path)

                    # 获取图片原始大小
                    img_width, img_height = bg_img.size
                    self.logger.info(f"背景图片原始大小: {img_width}x{img_height}")

                    # 缩小图片到合适大小
                    scale_factor = 0.125  # 缩小到原始大小的1/8
                    new_width = int(img_width * scale_factor)
                    new_height = int(img_height * scale_factor)
                    bg_img = bg_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    self.logger.info(f"背景图片缩小后大小: {new_width}x{new_height}")

                    # 更新图片大小变量
                    img_width, img_height = new_width, new_height

                    # 创建专门的背景轴，位于底层
                    bg_ax = fig.add_axes([0, 0, 1, 1], zorder=-1)
                    bg_ax.axis("off")

                    # 创建足够大的画布来平铺图片
                    # 计算需要平铺的次数
                    canvas_width = int(fig_width * 100)
                    canvas_height = int(fig_height * 100)

                    # 创建一个新的图像，用于平铺
                    tiled_img = Image.new("RGBA", (canvas_width, canvas_height))

                    # 平铺图片
                    for x in range(0, canvas_width, img_width):
                        for y in range(0, canvas_height, img_height):
                            tiled_img.paste(bg_img, (x, y))

                    # 显示平铺后的图片
                    bg_ax.imshow(tiled_img)

                    self.logger.info("背景图片加载成功（循环平铺）")
                else:
                    self.logger.error(f"背景图片文件不存在: {background_path}")
                    # 如果背景图片不存在，使用白色背景
                    ax.set_facecolor("#ffffff")
            else:
                self.logger.info("背景图片已禁用")
                # 如果禁用背景图片，使用白色背景
                ax.set_facecolor("#ffffff")
        except Exception as e:
            self.logger.error(f"加载背景图片失败: {e}")
            # 如果加载失败，使用白色背景
            ax.set_facecolor("#ffffff")

        # 隐藏坐标轴
        ax.axis("tight")
        ax.axis("off")

        # 创建表格，不显示周数列
        # 复制DataFrame并删除周数列
        df_no_week = self.df.copy()
        if "周次" in df_no_week.columns:
            df_no_week = df_no_week.drop("周次", axis=1)

        table = ax.table(
            cellText=df_no_week.values,
            colLabels=df_no_week.columns,
            cellLoc="center",
            loc="upper center",
        )

        # 设置表格样式
        table.auto_set_font_size(False)
        table.set_fontsize(image_config["font_size"])
        table.scale(image_config["table_scale_x"], image_config["table_scale_y"])

        # 自动调整列宽以适应内容
        table.auto_set_column_width(col=list(range(len(df_no_week.columns))))

        # 从CSV文件名中提取周数
        csv_basename = os.path.basename(self.csv_file)
        week_number = (
            csv_basename.split("_week")[1].split(".")[0] if "_week" in csv_basename else "1"
        )

        # 使用配置生成标题
        title_format = image_config["title_format"]
        title = title_format.format(class_name=class_name, week_number=week_number)

        # 设置表格标题（显式指定中文字体）
        plt.title(
            title,
            fontsize=image_config["title_font_size"],
            pad=10,
            fontweight="bold",
            fontproperties=self.chinese_font,
        )

        # 从配置中获取着色模式和星期颜色
        color_mode = image_config.get("color_mode", "row")
        weekday_colors = image_config.get("weekday_colors", {})

        # 调整表格单元格样式
        for (i, _j), cell in table.get_celld().items():
            if i == 0:  # 表头
                # 根据是否启用背景图片决定表头背景色
                if enable_background:
                    # 启用背景图片时，使用半透明背景（提高不透明度）
                    cell.set_facecolor("#4CAF50CC")  # 绿色带75%不透明度
                else:
                    # 禁用背景图片时，使用不透明背景
                    cell.set_facecolor(image_config["header_bg_color"])  # 不透明绿色
                cell.set_text_props(fontweight="bold", color="white")
            else:  # 数据行
                if color_mode == "weekday":  # 按星期着色
                    # 获取当前行的星期
                    weekday = df_no_week.iloc[i - 1]["星期"]
                    # 获取对应星期的颜色
                    weekday_color = weekday_colors.get(weekday, "#ffffff")

                    if enable_background:
                        # 启用背景图片时，使用半透明背景
                        # 将颜色转换为带透明度的格式
                        if len(weekday_color) == 7:  # #RRGGBB格式
                            alpha = "CC"  # 75%不透明度
                            transparent_color = weekday_color + alpha
                        else:
                            transparent_color = weekday_color
                        cell.set_facecolor(transparent_color)
                    else:
                        # 禁用背景图片时，使用不透明背景
                        cell.set_facecolor(weekday_color)
                else:  # 按行交替着色
                    if enable_background:
                        # 启用背景图片时，使用半透明背景（提高不透明度）
                        if i % 2 == 0:
                            cell.set_facecolor("#E3F2FDCC")  # 浅蓝色带75%不透明度
                        else:
                            cell.set_facecolor("#FFFFFFCC")  # 白色带75%不透明度
                    else:
                        # 禁用背景图片时，使用不透明背景
                        if i % 2 == 0:
                            cell.set_facecolor(image_config["even_row_color"])  # 不透明浅蓝色
                        else:
                            cell.set_facecolor(image_config["odd_row_color"])  # 不透明白色
            cell.set_edgecolor(image_config["border_color"])
            cell.set_linewidth(0.5)
            # 为所有单元格设置中文字体
            cell.set_fontsize(image_config["font_size"])
            cell.set_text_props(fontproperties=self.chinese_font)

        # 调整布局，最小化空白区域
        plt.subplots_adjust(top=0.95, bottom=0.01, left=0.01, right=0.99)

        # 生成文件名
        if not filename:
            # 从CSV文件名中提取周数
            csv_basename = os.path.basename(self.csv_file)
            week_number = (
                csv_basename.split("_week")[1].split(".")[0] if "_week" in csv_basename else "1"
            )
            filename_format = image_config["filename_format"]
            filename = filename_format.format(class_name=class_name, week_number=week_number)

        # 保存图片
        output_path = os.path.join(self.abs_output_dir, filename)

        # 备份所有旧图片
        self._backup_all_old_images(self.abs_output_dir, filename)

        plt.savefig(output_path, dpi=image_config["dpi"], bbox_inches="tight", pad_inches=0.1)
        plt.close()

        self.logger.info(f"图片已生成: {output_path}")
        return output_path

    def _generate_empty_placeholder(self, filename=None):
        """
        数据为空时（如学期尚未排课）生成空白占位图，
        避免 matplotlib 渲染空表格（cellText[0] 越界）导致整个爬取任务崩溃。
        """
        image_config = CONFIG["image"]
        class_name = CONFIG["class_name"]

        # 从CSV文件名中提取周数（用于标题）
        csv_basename = os.path.basename(self.csv_file)
        week_number = (
            csv_basename.split("_week")[1].split(".")[0] if "_week" in csv_basename else "1"
        )
        title_format = image_config["title_format"]
        title = title_format.format(class_name=class_name, week_number=week_number)

        fig, ax = plt.subplots(figsize=(10, 3))
        ax.axis("off")
        plt.title(
            title,
            fontsize=image_config["title_font_size"],
            pad=10,
            fontweight="bold",
            fontproperties=self.chinese_font,
        )
        ax.text(
            0.5,
            0.45,
            "暂无排课数据\n（本学期可能尚未排课）",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=image_config["title_font_size"],
            fontproperties=self.chinese_font,
            color="#888888",
        )
        plt.subplots_adjust(top=0.85, bottom=0.05, left=0.05, right=0.95)

        if not filename:
            filename_format = image_config["filename_format"]
            filename = filename_format.format(class_name=class_name, week_number=week_number)

        output_path = os.path.join(self.abs_output_dir, filename)
        # 备份所有旧图片
        self._backup_all_old_images(self.abs_output_dir, filename)

        plt.savefig(output_path, dpi=image_config["dpi"], bbox_inches="tight", pad_inches=0.1)
        plt.close()
        self.logger.info(f"空白占位图已生成: {output_path}")
        return output_path

    def run(self):
        """
        执行完整的转换流程
        """
        if self.load_csv():
            # 生成纵向布局图片
            vertical_image = self.generate_image()
            return vertical_image
        return None


if __name__ == "__main__":
    # 初始化日志记录器
    main_logger = get_logger("image")

    # 默认处理最新的处理后CSV文件
    processed_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "output", "course-data", "processed")
    )
    csv_files = [f for f in os.listdir(processed_dir) if f.endswith(".csv") and "_week" in f]

    if csv_files:
        # 按修改时间排序，取最新的文件
        csv_files.sort(key=lambda x: os.path.getmtime(os.path.join(processed_dir, x)), reverse=True)
        latest_csv = os.path.join(processed_dir, csv_files[0])
        main_logger.info(f"使用最新的CSV文件: {latest_csv}")

        converter = CsvToImage(latest_csv)
        converter.run()
    else:
        main_logger.error("未找到处理后的CSV文件")
        main_logger.error("请先运行课程处理程序生成处理后的CSV文件")
