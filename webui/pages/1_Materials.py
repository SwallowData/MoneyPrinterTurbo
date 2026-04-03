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


def render_material_gallery(materials, cols=4):
    """以图片画廊形式渲染素材"""
    if not materials:
        st.info("没有找到匹配的素材")
        return

    # 分列显示
    for i, material in enumerate(materials):
        with st.container():
            # 渲染图片/视频
            if material.file_type == "video":
                if material.thumbnail_path and os.path.exists(material.thumbnail_path):
                    st.image(material.thumbnail_path, use_container_width=True)
                else:
                    st.video(material.file_path, start_time=0)
            else:
                st.image(material.file_path, use_container_width=True)

            # 左上角编号
            st.markdown(
                f"""
                <div style="position: relative; margin-top: -60px; margin-left: 8px;">
                    <span style="background: rgba(0,0,0,0.6); color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;">
                        #{i + 1}
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # 描述在图片下方
            if material.description:
                desc_text = material.description[:80] + "..." if len(material.description) > 80 else material.description
                st.caption(f"📝 {desc_text}")
            else:
                st.caption("📝 无描述")

            # 关键词标签
            if material.keywords:
                keywords_str = " ".join([f"`{k}`" for k in material.keywords[:5]])
                st.markdown(f"<div style='font-size:11px; color: #666;'>{keywords_str}</div>", unsafe_allow_html=True)

            # 底部信息
            info_col1, info_col2, info_col3 = st.columns(3)
            with info_col1:
                st.caption(f"👁 {material.use_count}次")
            with info_col2:
                st.caption(f"📦 {material.source}")
            with info_col3:
                if material.duration:
                    st.caption(f"⏱ {material.duration:.1f}s")

            st.divider()


def render_material_list(materials):
    """以列表形式渲染素材（兼容模式）"""
    if not materials:
        st.info("没有找到匹配的素材")
        return

    for idx, material in enumerate(materials):
        with st.container(border=True):
            col1, col2 = st.columns([1, 3])

            with col1:
                if material.file_type == "video":
                    if material.thumbnail_path and os.path.exists(material.thumbnail_path):
                        st.image(material.thumbnail_path, width=120)
                    else:
                        st.video(material.file_path, start_time=0)
                else:
                    st.image(material.file_path, width=120)
                st.caption(f"**#{idx + 1}**")

            with col2:
                if material.description:
                    st.write(f"**描述**: {material.description[:150]}..." if len(material.description) > 150 else f"**描述**: {material.description}")
                if material.keywords:
                    st.write(f"**关键词**: {' '.join([f'`{k}`' for k in material.keywords[:8]])}")

                info_cols = st.columns(4)
                with info_cols[0]:
                    st.metric("使用", material.use_count)
                with info_cols[1]:
                    st.write(f"**来源**: {material.source}")
                with info_cols[2]:
                    st.write(f"**类型**: {material.file_type}")
                with info_cols[3]:
                    if material.duration:
                        st.write(f"**时长**: {material.duration:.1f}s")


# 页面标题
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

# 显示模式切换
view_mode = st.radio(
    "显示模式",
    ["画廊", "列表"],
    horizontal=True,
    index=0,
)

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

# 根据显示模式渲染
if view_mode == "画廊":
    # 画廊模式：计算列数
    cols = st.slider("每行显示", min_value=2, max_value=6, value=4)

    # 分行显示
    rows = [filtered_materials[i:i+cols] for i in range(0, len(filtered_materials), cols)]

    for row in rows:
        cols_list = st.columns(len(row))
        for col_idx, material in enumerate(row):
            with cols_list[col_idx]:
                # 全局索引
                global_idx = filtered_materials.index(material)

                # 渲染图片/视频
                if material.file_type == "video":
                    if material.thumbnail_path and os.path.exists(material.thumbnail_path):
                        st.image(material.thumbnail_path, use_container_width=True)
                    else:
                        st.video(material.file_path, start_time=0)
                else:
                    st.image(material.file_path, use_container_width=True)

                # 左上角编号
                st.markdown(
                    f"""
                    <div style="position: relative; margin-top: -50px; margin-left: 4px;">
                        <span style="background: rgba(0,0,0,0.7); color: white; padding: 1px 6px; border-radius: 3px; font-size: 11px;">
                            #{global_idx + 1}
                        </span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # 描述在图片下方
                if material.description:
                    desc_text = material.description[:60] + "..." if len(material.description) > 60 else material.description
                    st.caption(f"📝 {desc_text}")
                else:
                    st.caption("📝 无描述")

                # 底部信息行
                info1, info2, info3 = st.columns(3)
                with info1:
                    st.caption(f"👁{material.use_count}")
                with info2:
                    st.caption(f"📦{material.source}")
                with info3:
                    if material.duration:
                        st.caption(f"⏱{material.duration:.1f}s")
else:
    render_material_list(filtered_materials)
