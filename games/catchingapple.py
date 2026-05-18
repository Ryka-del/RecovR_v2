import pygame
import os
import random

# ----------------------------
# INIT
# ----------------------------
pygame.init()
pygame.mixer.init()

FPS = 60
BASKET_SPEED = 8
APPLE_SPEED = 4

MAX_LIVES = 6
SHAKE_DURATION = 300
BLAST_DURATION = 150
TOAST_DURATION = 800

SCREEN = pygame.display.set_mode((1000, 600), pygame.RESIZABLE)
pygame.display.set_caption("Catching Apple Game")
clock = pygame.time.Clock()

# ----------------------------
# COLORS & FONTS
# ----------------------------
SOFT_WHITE = (245, 245, 245)
DARK_GRAY  = (0, 0, 0)

FONT_PATH  = os.path.join("assets", "font", "Fredoka-Regular.ttf")
SCORE_FONT = pygame.font.Font(FONT_PATH, 35)
SCORE_FONT.set_bold(True)
TOAST_FONT = pygame.font.Font(FONT_PATH, 25)
TOAST_FONT.set_bold(True)

# ----------------------------
# IMAGES
# ----------------------------
def load_image(name, size):
    path = os.path.join("assets", "images", name)
    return pygame.transform.scale(pygame.image.load(path), size)

BASKET_IMG = load_image("basket.png", (100, 100))
APPLE_IMG  = load_image("apple.png", (50, 50))
HEART_IMG  = load_image("heart.png", (35, 35))
BLAST_IMG  = load_image("blast.png", (80, 80))
TOAST_ICON = load_image("apple.png", (24, 24))
GAME_OVER_IMG = load_image("game_over.png", (250, 250))
BG_IMG = pygame.image.load(os.path.join("assets", "images", "catching_game_bg.jpg")).convert()
TOAST_BG = load_image("cloud_message.png", (250, 100))
SCORE_BG = load_image("score_background.png", (220, 100))
# ----------------------------
# SOUNDS
# ----------------------------
def load_sound(name):
    return pygame.mixer.Sound(os.path.join("assets", "audio", name))

CATCH_SOUND = load_sound("catch_sound_effect.wav")
BLAST_SOUND = load_sound("blast_sound.wav")
GAME_OVER_SOUND = load_sound("game_over_sound.wav")

# ----------------------------
# HELPERS
# ----------------------------
def create_basket():
    rect = BASKET_IMG.get_rect()
    rect.centerx = SCREEN.get_width() // 2
    rect.bottom  = SCREEN.get_height()
    return rect

def create_apple():
    rect = APPLE_IMG.get_rect()
    rect.x = random.randint(0, SCREEN.get_width() - rect.width)
    rect.y = 0
    return rect

def get_heart_positions():
    return [(10 + i * 40, 85) for i in range(MAX_LIVES)]

def elapsed(start):
    return pygame.time.get_ticks() - start

# ----------------------------
# UI
# ----------------------------
def draw_score(score):
    text = SCORE_FONT.render(f"Score: {score}", True, DARK_GRAY)

    panel_x = 10
    panel_y = 10

    SCREEN.blit(SCORE_BG, (panel_x, panel_y))

    text_x = panel_x + (SCORE_BG.get_width()  - text.get_width())  // 2
    text_y = panel_y + (SCORE_BG.get_height() - text.get_height()) // 2

    SCREEN.blit(text, (text_x, text_y))

def draw_hearts(lives, shaking, shake_offset):
    for i, (x, y) in enumerate(get_heart_positions()):
        if i < lives:
            offset = shake_offset if shaking else 0
            SCREEN.blit(HEART_IMG, (x + offset, y))

def draw_blast(pos):
    SCREEN.blit(BLAST_IMG, pos)

def draw_toast(basket):
    label = TOAST_FONT.render("Nice Catch +1", True, DARK_GRAY)

    gap     = 8
    total_w = label.get_width() + gap + TOAST_ICON.get_width()
    row_h   = max(label.get_height(), TOAST_ICON.get_height())

    # Center panel above basket
    panel_x = basket.centerx - TOAST_BG.get_width() // 2
    panel_y = basket.top - TOAST_BG.get_height() - 5

    # Draw panel first
    SCREEN.blit(TOAST_BG, (panel_x, panel_y))

    # Center text+icon inside the panel
    content_x = panel_x + (TOAST_BG.get_width() - total_w) // 2
    content_y = panel_y + (TOAST_BG.get_height() - row_h) // 2

    SCREEN.blit(label,      (content_x, content_y + (row_h - label.get_height()) // 2))
    SCREEN.blit(TOAST_ICON, (content_x + label.get_width() + gap,
                              content_y + (row_h - TOAST_ICON.get_height()) // 2))

def draw_game_over():
    bg = pygame.transform.scale(BG_IMG, SCREEN.get_size())
    SCREEN.blit(bg, (0, 0))

    x = SCREEN.get_width() // 2 - GAME_OVER_IMG.get_width() // 2
    y = SCREEN.get_height() // 2 - GAME_OVER_IMG.get_height() // 2

    SCREEN.blit(GAME_OVER_IMG, (x, y))
    pygame.display.update()

# ----------------------------
# MAIN GAME DRAW
# ----------------------------
def draw_game(basket, apple, score, lives,
              shaking, shake_offset,
              blast_active, blast_start, blast_pos,
              toast_active, toast_start):

    bg = pygame.transform.scale(BG_IMG, SCREEN.get_size())
    SCREEN.blit(bg, (0, 0))

    SCREEN.blit(APPLE_IMG, apple)
    SCREEN.blit(BASKET_IMG, basket)

    draw_score(score)
    draw_hearts(lives, shaking, shake_offset)

    if blast_active and elapsed(blast_start) < BLAST_DURATION:
        SCREEN.blit(BLAST_IMG, blast_pos)

    if toast_active and elapsed(toast_start) < TOAST_DURATION:
        draw_toast(basket)

    pygame.display.update()

# ----------------------------
# MAIN LOOP
# ----------------------------
def main():
    global SCREEN

    basket = create_basket()
    apple  = create_apple()

    score = 0
    lives = MAX_LIVES

    game_state = "playing"
    game_over_sound_played = False

    blast_active = False
    blast_start  = 0
    blast_pos    = (0, 0)

    toast_active = False
    toast_start  = 0

    shaking = False
    shake_start = 0
    shake_offset = 0

    running = True
    while running:
        clock.tick(FPS)

        # ----------------------------
        # EVENTS
        # ----------------------------
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.VIDEORESIZE:
                SCREEN = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                basket = create_basket()
                apple = create_apple()

        # ----------------------------
        # GAME OVER CHECK
        # ----------------------------
        if lives <= 0:
            game_state = "game_over"

        # ----------------------------
        # UPDATE
        # ----------------------------
        if game_state == "playing":

            keys = pygame.key.get_pressed()
            if keys[pygame.K_LEFT]:
                basket.x -= BASKET_SPEED
            if keys[pygame.K_RIGHT]:
                basket.x += BASKET_SPEED

            basket.x = max(0, min(basket.x, SCREEN.get_width() - basket.width))

            apple.y += APPLE_SPEED

            previous_lives = lives

            # catch
            if basket.colliderect(apple):
                score += 1
                toast_active = True
                toast_start = pygame.time.get_ticks()
                CATCH_SOUND.play()
                apple = create_apple()

            # miss
            missed_x = apple.x
            if apple.y > SCREEN.get_height():
                lives -= 1
                apple = create_apple()

            # blast
            if lives < previous_lives:
                blast_x = missed_x - (BLAST_IMG.get_width() - APPLE_IMG.get_width()) // 2
                blast_pos = (blast_x, SCREEN.get_height() - BLAST_IMG.get_height())

                blast_active = True
                blast_start = pygame.time.get_ticks()
                BLAST_SOUND.play()

                shaking = True
                shake_start = pygame.time.get_ticks()

        # ----------------------------
        # SHAKE
        # ----------------------------
        if shaking and elapsed(shake_start) < SHAKE_DURATION:
            shake_offset = random.randint(-4, 4)
        else:
            shaking = False
            shake_offset = 0

        # ----------------------------
        # RENDER
        # ----------------------------
        if game_state == "playing":
            draw_game(
                basket, apple, score, lives,
                shaking, shake_offset,
                blast_active, blast_start, blast_pos,
                toast_active, toast_start
            )
        else:
            if not game_over_sound_played:
                GAME_OVER_SOUND.play()
                game_over_sound_played = True

            draw_game_over()

    pygame.quit()

# ----------------------------
# START
# ----------------------------
if __name__ == "__main__":
    main()