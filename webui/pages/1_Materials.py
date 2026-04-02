"""
素材库管理页面
提供素材的浏览、搜索、预览和管理功能
"""
import os
import sys

import streamlit as st

# Add the root directory of the project to the system path
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from app.services.material_db import get_material_db
from app.models.material import Material


def render_material_card(material: Material):
    """渲染单个素材卡片"""
    col1, col2 = st.columns([1, 3])

    with col1:
        if material.file_type == "video":
            # 显示缩略图或视频
            if material.thumbnail_path and os.path.exists(material.thumbnail_path):
                st.image(material.thumbnail_path, width=150)
            else:
                st.video(material.file_path, start_time=0)
        else:
            st.image(material.file_path, width=150)

    with col2:
        st.write(f"**文件路径**: `{material.file_path}`")
        if material.description:
            st.write(f"**描述**: {material.description[:200]}..." if len(material.description) > 200 else f"**描述**: {material.description}")

        if material.keywords:
            st.write(f"**关键词**: {' '.join([f'`{k}`' for k in material.keywords[:8]])}")

        col_info = st.columns(4)
        with col_info[0]:
            st.metric("使用次数", material.use_count)
        with col_info[1]:
            st.write(f"**来源**: {material.source}")
        with col_info[2]:
            st.write(f"**类型**: {material.file_type}")
        with col_info[3]:
            if material.duration:
                st.write(f"**时长**: {material.duration:.1f}s")


def main():
    st.set_page_config(
        page_title="素材库管理",
        page_icon="🗃️",
        layout="wide",
    )

    st.title("🗃️ 素材库管理")

    # 初始化数据库
    db = get_material_db()

    # 统计信息
    total = db.count()
    video_count = db.count("video")
    image_count = db.count("image")

    stat_col1, stat_col2, stat_col3 = st.columns(3)
    stat_col1.metric("总素材数", total)
    stat_col2.metric("视频", video_count)
    stat_col3.metric("图片", image_count)

    st.divider()

    # 筛选区域
    filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 2])

    with filter_col1:
        source_filter = st.selectbox(
            "来源筛选",
            ["全部", "pexels", "pixabay", "local"],
            index=0,
        )

    with filter_col2:
        type_filter = st.selectbox(
            "类型筛选",
            ["全部", "video", "image"],
            index=0,
        )

    with filter_col3:
        search_text = st.text_input("搜索描述/关键词", placeholder="输入关键词搜索...")

    st.divider()

    # 获取素材列表
    materials = db.get_all(limit=500)

    # 应用筛选
    filtered_materials = []
    for m in materials:
        # 来源筛选
        if source_filter != "全部" and m.source != source_filter:
            continue
        # 类型筛选
        if type_filter != "全部" and m.file_type != type_filter:
            continue
        # 关键词搜索
        if search_text:
            search_lower = search_text.lower()
            matched = False
            if search_lower in m.description.lower():
                matched = True
            for kw in m.keywords:
                if search_lower in kw.lower():
                    matched = True
                    break
            if not matched:
                continue
        filtered_materials.append(m)

    # 显示结果数量
    st.write(f"**显示 {len(filtered_materials)} / {len(materials)} 条记录**")

    # 渲染素材列表
    if not filtered_materials:
        st.info("没有找到匹配的素材")
    else:
        for material in filtered_materials:
            with st.container(border=True):
                render_material_card(material)
                st.divider()


if __name__ == "__main__":
    main()
