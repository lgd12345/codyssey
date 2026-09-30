import json
import os


# ==================================================
# 기본 프롬프트 데이터
# ==================================================

DEFAULT_PROMPTS = [
    {
        "title": "블로그 글 작성 도우미",
        "content": "주어진 주제에 대해 이해하기 쉬운 블로그 글을 작성해주세요.",
        "category": "텍스트 생성",
        "favorite": False,
    },
    {
        "title": "제품 이미지 생성",
        "content": "제품의 특징이 잘 드러나는 광고 이미지를 생성해주세요.",
        "category": "이미지 생성",
        "favorite": False,
    },
    {
        "title": "IT 전문가 페르소나",
        "content": "당신은 친절하고 경험이 풍부한 IT 전문가입니다.",
        "category": "페르소나",
        "favorite": True,
    },
]


CATEGORIES = [
    "텍스트 생성",
    "이미지 생성",
    "영상 생성",
    "페르소나",
    "자동화",
    "기타",
    "직접 입력",
]


DATA_FILE = "prompts.json"


# ==================================================
# JSON 저장 / 불러오기
# ==================================================

def save_prompts():
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(
            prompts,
            file,
            ensure_ascii=False,
            indent=2
        )


def load_prompts():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

            if isinstance(data, list):
                return data

    except (FileNotFoundError, json.JSONDecodeError):
        pass

    return [prompt.copy() for prompt in DEFAULT_PROMPTS]


prompts = load_prompts()


# ==================================================
# 공통 화면 출력
# ==================================================

def print_header(title):
    print("\n" + "=" * 45)
    print(f" {title}")
    print("=" * 45)


def print_exit_message():
    save_prompts()

    print("\n" + "=" * 45)
    print(" 프로그램을 종료합니다.")
    print("=" * 45)


def next_action():
    while True:
        print("\n" + "-" * 45)
        print("[M] 메인 메뉴  |  [0] 프로그램 종료")
        print("-" * 45)

        choice = input("선택: ").strip().lower()

        if choice == "m":
            return "menu"

        if choice == "0":
            return "exit"

        print("M 또는 0을 입력해주세요.")


# ==================================================
# 메인 메뉴
# ==================================================

def show_menu():
    print_header("나만의 프롬프트 관리")

    print("1. 프롬프트 추가")
    print("2. 프롬프트 목록")
    print("3. 카테고리별 조회")
    print("4. 프롬프트 검색")
    print("5. 프롬프트 상세 보기")
    print("6. 즐겨찾기 관리")
    print("7. 즐겨찾기 목록")
    print("8. Markdown 내보내기")

    print("-" * 45)
    print("0. 프로그램 종료")
    print("=" * 45)


# ==================================================
# 프롬프트 추가
# ==================================================

def add_prompt():
    print_header("프롬프트 추가")

    print("[M] 메인 메뉴  |  [0] 프로그램 종료")
    print("-" * 45)

    # 제목 입력
    while True:
        title = input("제목: ").strip()

        if title.lower() == "m":
            return "menu"

        if title == "0":
            return "exit"

        if title:
            break

        print("제목을 입력해주세요.")

    # 내용 입력
    while True:
        content = input("내용: ").strip()

        if content.lower() == "m":
            return "menu"

        if content == "0":
            return "exit"

        if content:
            break

        print("내용을 입력해주세요.")

    # 카테고리 선택
    print("\n" + "-" * 45)
    print("카테고리 선택")
    print("-" * 45)

    for i, category in enumerate(CATEGORIES, start=1):
        print(f"{i}. {category}")

    print("-" * 45)
    print("[M] 메인 메뉴  |  [0] 프로그램 종료")

    while True:
        choice = input("선택: ").strip()

        if choice.lower() == "m":
            return "menu"

        if choice == "0":
            return "exit"

        if not choice:
            print("카테고리를 선택하거나 직접 입력해주세요.")
            continue

        if not choice.isdigit():
            print("카테고리를 선택하거나 직접 입력해주세요.")
            continue

        choice_num = int(choice)

        if not 1 <= choice_num <= len(CATEGORIES):
            print("카테고리를 선택하거나 직접 입력해주세요.")
            continue

        selected = CATEGORIES[choice_num - 1]

        # 직접 입력 선택
        if selected == "직접 입력":
            while True:
                category = input("카테고리 직접 입력: ").strip()

                if category.lower() == "m":
                    return "menu"

                if category == "0":
                    return "exit"

                if category:
                    break

                print("카테고리를 입력해주세요.")

        else:
            category = selected

        break

    # 프롬프트 저장
    prompts.append(
        {
            "title": title,
            "content": content,
            "category": category,
            "favorite": False,
        }
    )

    save_prompts()

    print("\n" + "-" * 45)
    print(f"'{title}' 프롬프트가 추가되었습니다.")
    print("메인 메뉴로 돌아갑니다.")
    print("-" * 45)

    # 추가 완료 후 자동으로 메인 메뉴
    return "menu"


# ==================================================
# 프롬프트 목록
# ==================================================

def show_list():
    print_header("프롬프트 목록")

    if not prompts:
        print("등록된 프롬프트가 없습니다.")
        return

    for i, prompt in enumerate(prompts, start=1):
        favorite = " ⭐" if prompt["favorite"] else ""

        print(
            f"{i}. "
            f"[{prompt['category']}] "
            f"{prompt['title']}"
            f"{favorite}"
        )

    print("-" * 45)
    print(f"총 {len(prompts)}개의 프롬프트")


# ==================================================
# 사용 가능한 카테고리
# ==================================================

def get_available_categories():
    categories = []

    # 기본 카테고리
    for category in CATEGORIES:
        if category != "직접 입력":
            categories.append(category)

    # 사용자가 직접 만든 카테고리
    for prompt in prompts:
        if prompt["category"] not in categories:
            categories.append(prompt["category"])

    return categories


# ==================================================
# 카테고리별 조회
# ==================================================

def show_by_category():
    print_header("카테고리별 조회")

    if not prompts:
        print("등록된 프롬프트가 없습니다.")
        return

    categories = get_available_categories()

    for i, category in enumerate(categories, start=1):
        print(f"{i}. {category}")

    while True:
        choice = input("\n선택: ").strip()

        if not choice:
            print("카테고리를 선택해주세요.")
            continue

        if not choice.isdigit():
            print("올바른 번호를 입력해주세요.")
            continue

        choice_num = int(choice)

        if not 1 <= choice_num <= len(categories):
            print("올바른 번호를 입력해주세요.")
            continue

        selected_category = categories[choice_num - 1]
        break

    results = []

    for prompt in prompts:
        if prompt["category"] == selected_category:
            results.append(prompt)

    print("\n" + "-" * 45)
    print(f"[{selected_category}] 카테고리 프롬프트")
    print("-" * 45)

    if not results:
        print("해당 카테고리의 프롬프트가 없습니다.")
        return

    for i, prompt in enumerate(results, start=1):
        favorite = " ⭐" if prompt["favorite"] else ""

        print(
            f"{i}. "
            f"{prompt['title']}"
            f"{favorite}"
        )

    print("-" * 45)
    print(f"총 {len(results)}개의 프롬프트")


# ==================================================
# 프롬프트 검색
# ==================================================

def search_prompt():
    print_header("프롬프트 검색")

    while True:
        keyword = input("검색어: ").strip()

        if keyword:
            break

        print("검색어를 입력해주세요.")

    keyword_lower = keyword.lower()
    results = []

    for prompt in prompts:
        if (
            keyword_lower in prompt["title"].lower()
            or keyword_lower in prompt["content"].lower()
        ):
            results.append(prompt)

    print("\n" + "-" * 45)
    print("검색 결과")
    print("-" * 45)

    if not results:
        print("검색 결과가 없습니다.")
        return

    for i, prompt in enumerate(results, start=1):
        favorite = " ⭐" if prompt["favorite"] else ""

        print(
            f"{i}. "
            f"[{prompt['category']}] "
            f"{prompt['title']}"
            f"{favorite}"
        )

    print("-" * 45)
    print(f"총 {len(results)}개의 프롬프트를 찾았습니다.")


# ==================================================
# 프롬프트 번호 선택
# ==================================================

def select_prompt():
    if not prompts:
        print("등록된 프롬프트가 없습니다.")
        return None

    show_list()

    while True:
        choice = input("\n프롬프트 번호 입력: ").strip()

        if not choice:
            print("프롬프트 번호를 입력해주세요.")
            continue

        if not choice.isdigit():
            print("올바른 번호를 입력해주세요.")
            continue

        prompt_num = int(choice)

        if not 1 <= prompt_num <= len(prompts):
            print("존재하지 않는 프롬프트 번호입니다.")
            continue

        return prompt_num - 1


# ==================================================
# 프롬프트 상세 보기
# ==================================================

def show_detail():
    print_header("프롬프트 상세 보기")

    index = select_prompt()

    if index is None:
        return

    prompt = prompts[index]

    favorite = "⭐ 즐겨찾기" if prompt["favorite"] else "일반"

    print("\n" + "=" * 45)
    print(f"제목     : {prompt['title']}")
    print(f"카테고리 : {prompt['category']}")
    print(f"즐겨찾기 : {favorite}")
    print("-" * 45)
    print("내용")
    print("-" * 45)
    print(prompt["content"])
    print("=" * 45)


# ==================================================
# 즐겨찾기 관리
# ==================================================

def toggle_favorite():
    print_header("즐겨찾기 관리")

    index = select_prompt()

    if index is None:
        return

    prompt = prompts[index]

    prompt["favorite"] = not prompt["favorite"]

    save_prompts()

    print("\n" + "-" * 45)

    if prompt["favorite"]:
        print(
            f"'{prompt['title']}' 프롬프트를 "
            "즐겨찾기에 추가했습니다."
        )

    else:
        print(
            f"'{prompt['title']}' 프롬프트의 "
            "즐겨찾기를 해제했습니다."
        )

    print("-" * 45)


# ==================================================
# 즐겨찾기 목록
# ==================================================

def show_favorites():
    print_header("즐겨찾기 목록")

    favorites = []

    for prompt in prompts:
        if prompt["favorite"]:
            favorites.append(prompt)

    if not favorites:
        print("즐겨찾기한 프롬프트가 없습니다.")
        return

    for i, prompt in enumerate(favorites, start=1):
        print(
            f"{i}. "
            f"[{prompt['category']}] "
            f"{prompt['title']} ⭐"
        )

    print("-" * 45)
    print(f"총 {len(favorites)}개의 즐겨찾기")


# ==================================================
# Markdown 내보내기
# ==================================================

def export_markdown():
    print_header("Markdown 내보내기")

    if not prompts:
        print("내보낼 프롬프트가 없습니다.")
        return

    export_folder = "exports"
    filename = "prompts_export.md"

    filepath = os.path.join(
        export_folder,
        filename
    )

    # exports 폴더가 없으면 자동 생성
    os.makedirs(
        export_folder,
        exist_ok=True
    )

    categories = []

    for prompt in prompts:
        if prompt["category"] not in categories:
            categories.append(prompt["category"])

    with open(
        filepath,
        "w",
        encoding="utf-8"
    ) as file:

        file.write("# 프롬프트 목록\n\n")

        for category in categories:
            file.write(f"## {category}\n\n")

            for prompt in prompts:
                if prompt["category"] == category:

                    favorite = (
                        " ⭐"
                        if prompt["favorite"]
                        else ""
                    )

                    file.write(
                        f"### {prompt['title']}"
                        f"{favorite}\n\n"
                    )

                    file.write(
                        f"{prompt['content']}\n\n"
                    )

    print("\n" + "-" * 45)
    print(f"'{filepath}' 파일로 내보냈습니다.")
    print("-" * 45)


# ==================================================
# 메인 프로그램
# ==================================================

def main():
    while True:

        # 메인 메뉴 출력
        show_menu()

        # 메뉴 선택
        while True:
            choice = input("선택: ").strip()

            # ------------------------------------------
            # 1. 프롬프트 추가
            # 추가 완료 후 자동으로 메인 메뉴 복귀
            # ------------------------------------------

            if choice == "1":
                action = add_prompt()

                if action == "exit":
                    print_exit_message()
                    return

                # 추가 완료 또는 M 입력
                # 바로 메인 메뉴로 이동
                break

            # ------------------------------------------
            # 2. 프롬프트 목록
            # ------------------------------------------

            elif choice == "2":
                show_list()
                action = next_action()

            # ------------------------------------------
            # 3. 카테고리별 조회
            # ------------------------------------------

            elif choice == "3":
                show_by_category()
                action = next_action()

            # ------------------------------------------
            # 4. 프롬프트 검색
            # ------------------------------------------

            elif choice == "4":
                search_prompt()
                action = next_action()

            # ------------------------------------------
            # 5. 상세 보기
            # ------------------------------------------

            elif choice == "5":
                show_detail()
                action = next_action()

            # ------------------------------------------
            # 6. 즐겨찾기 관리
            # ------------------------------------------

            elif choice == "6":
                toggle_favorite()
                action = next_action()

            # ------------------------------------------
            # 7. 즐겨찾기 목록
            # ------------------------------------------

            elif choice == "7":
                show_favorites()
                action = next_action()

            # ------------------------------------------
            # 8. Markdown 내보내기
            # ------------------------------------------

            elif choice == "8":
                export_markdown()
                action = next_action()

            # ------------------------------------------
            # 0. 종료
            # ------------------------------------------

            elif choice == "0":
                print_exit_message()
                return

            # ------------------------------------------
            # 잘못된 메뉴 입력
            # ------------------------------------------

            else:
                print("올바른 메뉴 번호를 입력해주세요.")
                continue

            # 기능 실행 후 0 선택
            if action == "exit":
                print_exit_message()
                return

            # M 선택 → 메인 메뉴로 이동
            break


# ==================================================
# 프로그램 시작
# ==================================================

if __name__ == "__main__":
    main()