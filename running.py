from engine import Engine

# Initialize app
app = Engine()



while running:
    hover_country = -1
    for i in range(42):
        for p in countries[i].polygon:
            transformed_coordinates = [transform_coordinates(v, zoom, xoffset, yoffset) for v in p]
            if players[turn].attack == 1 and players[turn].subattack == 1:
                if not countries[i].owner == players[turn] and np.any([attack_from in connection and i in connection for connection in connections]):
                    pg.draw.polygon(screen, np.clip(countries[i].owner.color + np.array([50, 50, 50]), 0, 255), transformed_coordinates)
                else:
                    pg.draw.polygon(screen, np.clip(countries[i].owner.color - np.array([50, 50, 50]), 0, 255), transformed_coordinates)
            elif players[turn].attack == 1 and players[turn].subattack > 1:
                if countries[i] == countries[attack_from] or countries[i] == countries[defence_country]:
                    pg.draw.polygon(screen, np.clip(countries[i].owner.color + np.array([50, 50, 50]), 0, 255), transformed_coordinates)
                else:
                    pg.draw.polygon(screen, np.clip(countries[i].owner.color - np.array([50, 50, 50]), 0, 255), transformed_coordinates)
            elif players[turn].attack == 2 and players[turn].subattack == 1:
                if countries[i].owner == players[turn]:# and countries[i] in finished_list:           #does not work yet, always takes else
                    pg.draw.polygon(screen, np.clip(countries[i].owner.color + np.array([50, 50, 50]), 0, 255), transformed_coordinates)
                else:
                    pg.draw.polygon(screen, np.clip(countries[i].owner.color - np.array([50, 50, 50]), 0, 255), transformed_coordinates)
            else:
                pg.draw.polygon(screen, countries[i].owner.color, transformed_coordinates)
            pg.draw.polygon(screen, (0,0,0), transformed_coordinates, 2)
            if pth.Path(p).contains_point(transformed_mouse_position):
                hover_country = i


    
    if players[turn].attack == 0:      #reinforcement phase
        if players[turn].subattack == 0:
            card_limit = 0
            initial_units = []
            for i in range(len(countries)):
                initial_units += [countries[i].units]
            units = 0
            players[turn].troops = 0
            new_food = 0
            starved = 0
            for i in range(len(countries)):
                if countries[i].owner == players[turn]:
                    units += countries[i].units
                    if countries[i].radioactive == 0:
                        players[turn].troops += countries[i].troops
                        players[turn].food += countries[i].food
                        new_food += countries[i].food
                        players[turn].wood += countries[i].wood
                        players[turn].steel += countries[i].steel
                        players[turn].oil += countries[i].oil
                        players[turn].nuclear += countries[i].nuclear
                    else:
                        countries[i].radioactive -= 1
            players[turn].food -= units
            if units == 0:
                turn = (turn + 1) % player_num
            elif players[turn].food - new_food < 0:
                starved = -(players[turn].food - new_food)
                players[turn].food = 0
            reinforcements = int((players[turn].troops - players[turn].troops%3)/3 + 3) - starved   #rounding down
            all_reinforcements_deployed = False
            attacked = []
            players[turn].subattack = 1
        pg.draw.rect(screen, (230,170,170), pg.Rect(WIDTH - 880, HEIGHT - 630, 60, 60))
        screen.blit(spr_cards, (WIDTH - 875, HEIGHT - 626))
        pg.draw.rect(screen, (0,170,0), pg.Rect(WIDTH - 935, HEIGHT - 270, 50, 50))
        screen.blit(myfont.render("+ "+str(reinforcements), False, (0, 0, 0)), (WIDTH - 920, HEIGHT - 200))
        pg.draw.rect(screen, (170,0,0), pg.Rect(WIDTH - 935, HEIGHT - 160, 50, 50))
        reward = 0
        if left_pressed and mouse_position[0] >= WIDTH - 880 and mouse_position[0] <= WIDTH - 820 and mouse_position[1] >= HEIGHT - 630 and mouse_position[1] <= HEIGHT - 570:
            attack = players[turn].attack
            subattack = players[turn].subattack
            players[turn].attack = 4
            players[turn].subattack = 0
        if players[turn].subattack == 1:    #adding units to countries
            if players[turn].start_ship and not checked:
                players[turn].attack = 6
                players[turn].subattack = 0
            pg.draw.rect(screen, (0,0,0), pg.Rect(25, HEIGHT - 270, 50, 50), 3)
            pg.draw.rect(screen, (0,0,0), pg.Rect(25, HEIGHT - 160, 50, 50), 1)
            if reinforcements <= 0:
                all_reinforcements_deployed = True
            if left_pressed and not hover_country == -1:
                if countries[hover_country].owner == players[turn] and all_reinforcements_deployed == False:
                    countries[hover_country].units += 1
                    reinforcements -= 1
            elif left_pressed and mouse_position[0] >= 25 and mouse_position[0] <= 75 and mouse_position[1] >= HEIGHT - 160 and mouse_position[1] <= HEIGHT - 110:
                players[turn].subattack = 2
        elif players[turn].subattack == 2:     #removing units from countries
            pg.draw.rect(screen, (0,0,0), pg.Rect(25, HEIGHT - 270, 50, 50), 1)
            pg.draw.rect(screen, (0,0,0), pg.Rect(25, HEIGHT - 160, 50, 50), 3)
            if left_pressed and not hover_country == -1:
                if countries[hover_country].owner == players[turn] and countries[hover_country].units > initial_units[hover_country]:
                    countries[hover_country].units -= 1
                    reinforcements += 1
                    if all_reinforcements_deployed:
                        all_reinforcements_deployed = False
            elif left_pressed and mouse_position[0] >= 25 and mouse_position[0] <= 75 and mouse_position[1] >= HEIGHT - 270 and mouse_position[1] <= HEIGHT - 220:
                players[turn].subattack = 1

    elif players[turn].attack == 1:      #attack phase
        if players[turn].subattack in [0,1,5]:
            pg.draw.rect(screen, (230,170,170), pg.Rect(WIDTH - 880, HEIGHT - 630, 60, 60))
            screen.blit(spr_cards, (WIDTH - 875, HEIGHT - 626))
            if left_pressed and mouse_position[0] >= WIDTH - 880 and mouse_position[0] <= WIDTH - 820 and mouse_position[1] >= HEIGHT - 630 and mouse_position[1] <= HEIGHT - 570:
                attack = players[turn].attack
                subattack = players[turn].subattack
                players[turn].attack = 4
                players[turn].subattack = 0
        if left_pressed and not hover_country == -1:
            if players[turn].subattack == 0:
                if countries[hover_country].owner == players[turn]:
                    players[turn].subattack = 1
                    attack_from = hover_country
            elif players[turn].subattack == 1:
                if hover_country == attack_from:
                    players[turn].subattack = 0
                if not countries[hover_country].owner == players[turn]:
                    if np.any([attack_from in connection and hover_country in connection and connection.kind == "land" for connection in connections]):
                        transport = [countries[attack_from].ships, countries[attack_from].planes]
                        attack_dice = np.zeros(min(countries[attack_from].units, 3))
                        defence_country = hover_country
                        defence_dice = np.zeros(min(countries[defence_country].units, 2))
                        players[turn].subattack = 2
                    elif np.any([attack_from in connection and hover_country in connection and connection.kind == "sea" for connection in connections]):
                        if countries[attack_from].ships > 0 or countries[attack_from].planes > 0:
                            transport = [countries[attack_from].ships, countries[attack_from].planes]
                            attack_dice = np.zeros(min(countries[attack_from].units, 3))
                            defence_country = hover_country
                            defence_dice = np.zeros(min(countries[defence_country].units, 2))
                            players[turn].subattack = 2
        if players[turn].subattack == 2:
            if np.all(attack_dice):
                players[turn].subattack = 0
            pg.draw.rect(screen, (100,100,100), pg.Rect(25, HEIGHT - 50, 200, 40))
            pg.draw.rect(screen, (0,0,0), pg.Rect(25, HEIGHT - 50, 200, 40), 3)
            for i in range(len(attack_dice)):
                pg.draw.rect(screen, (255, 50, 50), pg.Rect(WIDTH*0.5 - 200 + 80*i, HEIGHT - 200 + 40*attack_dice[i], 70, 70))
                pg.draw.rect(screen, (0, 0, 0), pg.Rect(WIDTH*0.5 - 200 + 80*i, HEIGHT - 200 + 40*attack_dice[i], 70, 70), 3)
                if left_pressed and mouse_position[0] >= WIDTH*0.5 - 200 + 80*i and mouse_position[0] <= WIDTH*0.5 - 200 + 80*i + 70 and mouse_position[1] >= HEIGHT - 200 + 40*attack_dice[i] and mouse_position[1] <= HEIGHT - 200 + 40*attack_dice[i] + 70:
                    attack_dice[i] = not attack_dice[i]
            if mouse_position[0] >= 25 and mouse_position[0] <= 225 and mouse_position[1] >= HEIGHT - 50 and mouse_position[1] <= HEIGHT - 10 and left_pressed:       #cast dice button location, to be determined
                for i in range(len(attack_dice)):
                    attack_dice[i] = (not attack_dice[i])*np.random.randint(1,7)
                players[turn].subattack = 3
        elif players[turn].subattack == 3:
            pg.draw.rect(screen, (100,100,100), pg.Rect(25, HEIGHT - 50, 200, 40))
            pg.draw.rect(screen, (0,0,0), pg.Rect(25, HEIGHT - 50, 200, 40), 3)
            for i in range(len(attack_dice)):
                if attack_dice[i] > 0:
                    pg.draw.rect(screen, (255, 50, 50), pg.Rect(WIDTH*0.5 - 200 + 80*i, 20, 70, 70))
                    pg.draw.rect(screen, (0, 0, 0), pg.Rect(WIDTH*0.5 - 200 + 80*i, 20, 70, 70), 3)
                    show_die(attack_dice[i], int(WIDTH*0.5) - 200 + 80*i + 35, 20 + 35)
            for i in range(len(defence_dice)):
                pg.draw.rect(screen, (0, 100, 255), pg.Rect(WIDTH*0.5 - 200 + 80*i, HEIGHT - 200 + 40*defence_dice[i], 70, 70))
                pg.draw.rect(screen, (0, 0, 0), pg.Rect(WIDTH*0.5 - 200 + 80*i, HEIGHT - 200 + 40*defence_dice[i], 70, 70), 3)
                if countries[defence_country].owner != default_player and left_pressed and mouse_position[0] >= WIDTH*0.5 - 200 + 80*i and mouse_position[0] <= WIDTH*0.5 - 200 + 80*i + 70 and mouse_position[1] >= HEIGHT - 200 + 40*defence_dice[i] and mouse_position[1] <= HEIGHT - 200 + 40*defence_dice[i] + 70:
                    defence_dice[i] = not defence_dice[i]
            if countries[defence_country].owner == default_player or (mouse_position[0] >= 25 and mouse_position[0] <= 225 and mouse_position[1] >= HEIGHT - 50 and mouse_position[1] <= HEIGHT - 10 and left_pressed and sum(not d for d in defence_dice) != 0):       #cast dice button location, to be determined
                for i in range(len(defence_dice)):
                    defence_dice[i] = (not defence_dice[i])*np.random.randint(1,7)
                players[turn].subattack = 4
                timer = 0
        elif players[turn].subattack == 4:
            for i in range(len(attack_dice)):
                if attack_dice[i] > 0:
                    pg.draw.rect(screen, (255, 50, 50), pg.Rect(WIDTH*0.5 - 200 + 80*i, 20, 70, 70))
                    pg.draw.rect(screen, (0, 0, 0), pg.Rect(WIDTH*0.5 - 200 + 80*i, 20, 70, 70), 3)
                    show_die(attack_dice[i], int(WIDTH*0.5) - 200 + 80*i + 35, 20 + 35)
            for i in range(len(defence_dice)):
                if defence_dice[i] > 0:
                    pg.draw.rect(screen, (0, 100, 255), pg.Rect(WIDTH*0.5 - 200 + 80*i, 100, 70, 70))
                    pg.draw.rect(screen, (0, 0, 0), pg.Rect(WIDTH*0.5 - 200 + 80*i, 100, 70, 70), 3)
                    show_die(defence_dice[i], int(WIDTH*0.5) - 200 + 80*i + 35, 100 + 35)
            if left_pressed:
                timer = 150
            if timer == 150:
                D = np.sort(defence_dice[defence_dice > 0]) + countries[defence_country].fort_lvl
                A = np.sort(attack_dice[attack_dice > 0])
                A[-1] += countries[attack_from].tanks   #still need a prompt for using tanks
                if not defence_country in attacked:
                    players[turn].oil -= countries[attack_from].tanks
                attacked += [defence_country]
                attack_loss = [A[-1-i] <= D[-1-i] for i in range(min(len(D), len(A)))]
                countries[attack_from].units -= sum(attack_loss)
                countries[defence_country].units -= sum(not a for a in attack_loss)
                if countries[defence_country].units == 0:
                    if countries[defence_country].owner != default_player and card_limit == 0:
                        card_drawn = np.random.randint(0,42)
                        for i in range(4):
                            if card_drawn >= 13*i and card_drawn < 13 + 13*i:
                                players[turn].cards += [i]
                                card_limit += 1
                                break
                    if np.any([transport[i] > 0 for i in range(2)]):
                        countries[defence_country].ships = countries[attack_from].ships   #would be better if this gave an option to leave ships/planes behind
                        countries[defence_country].planes = countries[attack_from].planes
                    if countries[defence_country].owner != default_player:
                        elimination = True
                        for i in range(len(countries)):
                            if countries[i].owner == countries[defence_country].owner and i != defence_country:
                                elimination = False
                                break
                        if elimination:
                            players[turn].wood += countries[defence_country].owner.wood
                            players[turn].steel += countries[defence_country].owner.steel
                            players[turn].nuclear += countries[defence_country].owner.nuclear
                            players[turn].oil += countries[defence_country].owner.oil
                            players[turn].cards += countries[defence_country].owner.cards
                            countries[defence_country].owner.wood = 0
                            countries[defence_country].owner.steel = 0
                            countries[defence_country].owner.nuclear = 0
                            countries[defence_country].owner.oil = 0
                            countries[defence_country].owner.cards = []
                    countries[defence_country].fort_lvl = 0
                    countries[defence_country].ships = countries[attack_from].ships
                    countries[defence_country].planes = countries[attack_from].planes
                    countries[defence_country].owner = players[turn]
                    countries[defence_country].units += len(A)
                    countries[attack_from].units -= len(A)
                    players[turn].subattack = 5
                else:
                    players[turn].subattack = 1
                    if countries[attack_from].units == 0:
                        countries[attack_from].units = 2
                        countries[attack_from].owner = default_player
            timer += 1
        elif players[turn].subattack == 5:
            pg.draw.rect(screen, (100,100,100), pg.Rect(25, HEIGHT - 50, 200, 40))
            pg.draw.rect(screen, (0,0,0), pg.Rect(25, HEIGHT - 50, 200, 40), 3)
            if left_pressed and not hover_country == -1:
                total_units = countries[defence_country].units + countries[attack_from].units
                if countries[hover_country] == countries[defence_country]:
                    if countries[defence_country].units + 1 > total_units or countries[attack_from].units - 1 < 0:
                        countries[defence_country].units = len(A)
                        countries[attack_from].units = total_units - len(A)
                    else:
                        countries[defence_country].units += 1
                        countries[attack_from].units -= 1
                if countries[hover_country] == countries[attack_from]:
                    if countries[defence_country].units - 1 < len(A) or countries[attack_from].units + 1 > total_units - len(A):
                        countries[defence_country].units = total_units
                        countries[attack_from].units = 0
                    else:
                        countries[defence_country].units -= 1
                        countries[attack_from].units += 1
            if mouse_position[0] >= 25 and mouse_position[0] <= 225 and mouse_position[1] >= HEIGHT - 50 and mouse_position[1] <= HEIGHT - 10 and left_pressed:
                players[turn].subattack = 0
                if countries[attack_from].units == 0:
                    countries[attack_from].units = 2
                    countries[attack_from].owner = default_player

    elif players[turn].attack == 2:       #movement phase
        if players[turn].subattack == 0:
            pg.draw.rect(screen, (230,170,170), pg.Rect(WIDTH - 880, HEIGHT - 630, 60, 60))
            screen.blit(spr_cards, (WIDTH - 875, HEIGHT - 626))
            if left_pressed and not hover_country == -1 and countries[hover_country].owner == players[turn]:
                origin_country = hover_country
                finished_list = [origin_country]
                while True:
                    oldlen = len(finished_list)
                    for country_ix in finished_list:
                        finished_list = np.union1d(finished_list, [l for l in set(np.array([list(con.connection) for con in connections if country_ix in con]).flatten()) if countries[l].owner == players[turn]])
                    if len(finished_list) == oldlen:
                        break
                players[turn].subattack = 1
            elif left_pressed and mouse_position[0] >= WIDTH - 880 and mouse_position[0] <= WIDTH - 820 and mouse_position[1] >= HEIGHT - 630 and mouse_position[1] <= HEIGHT - 570:
                attack = players[turn].attack
                subattack = players[turn].subattack
                players[turn].attack = 4
                players[turn].subattack = 0
        elif left_pressed and players[turn].subattack == 1:
            if hover_country in finished_list and hover_country != origin_country:
                target_country = hover_country
                total_units = countries[origin_country].units + countries[target_country].units + 1
                initial_origin = countries[origin_country].units
                initial_target = countries[target_country].units
                players[turn].subattack = 2
            elif hover_country == origin_country:
                players[turn].subattack = 0
        elif players[turn].subattack == 2:
            pg.draw.rect(screen, (170,0,0), pg.Rect(25, HEIGHT - 50, 100, 40))
            pg.draw.rect(screen, (0,0,0), pg.Rect(25, HEIGHT - 50, 100, 40), 3)
            if left_pressed and countries[hover_country] == countries[origin_country]:
                countries[origin_country].units = np.mod(countries[origin_country].units + 1, total_units)
                countries[target_country].units = np.mod(countries[target_country].units - 1, total_units)
            elif left_pressed and countries[hover_country] == countries[target_country]:
                countries[origin_country].units = np.mod(countries[origin_country].units - 1, total_units)
                countries[target_country].units = np.mod(countries[target_country].units + 1, total_units)
            elif mouse_position[0] >= 25 and mouse_position[0] <= 125 and mouse_position[1] >= HEIGHT - 50 and mouse_position[1] <= HEIGHT - 10 and left_pressed:
                players[turn].subattack = 0
                countries[origin_country].units = initial_origin
                countries[target_country].units = initial_target
            elif mouse_position[0] >= WIDTH - 200 + 70*min(players[turn].attack + 1, 2) and mouse_position[0] <= WIDTH - 200 + 70*min(players[turn].attack + 1, 2) + 60 and mouse_position[1] >= HEIGHT - 50 and mouse_position[1] <= HEIGHT - 10 and left_pressed:
                if countries[origin_country].units == 0:
                    countries[origin_country].units = 2
                    countries[origin_country].owner = default_player
                elif countries[target_country].units == 0:
                    countries[target_country].units = 2
                    countries[target_country].owner = default_player
    if left_pressed and not players[turn].attack == 3 and mouse_position[0] >= WIDTH - 950 and mouse_position[0] <= WIDTH - 890 and mouse_position[1] >= HEIGHT - 630 and mouse_position[1] <= HEIGHT - 570:
        attack = players[turn].attack
        subattack = players[turn].subattack
        players[turn].attack = 3
        players[turn].subattack = 0

    if players[turn].attack == 3:       #shop
        if attack == 0 or attack == 4:
            pg.draw.rect(screen, (230,170,170), pg.Rect(WIDTH - 880, HEIGHT - 630, 60, 60))
            screen.blit(spr_cards, (WIDTH - 875, HEIGHT - 626))
            pg.draw.rect(screen, (0,170,0), pg.Rect(WIDTH - 935, HEIGHT - 270, 50, 50))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 935, HEIGHT - 270, 50, 50), 3)
            screen.blit(myfont.render("+ "+str(reinforcements), False, (0, 0, 0)), (WIDTH - 920, HEIGHT - 200))
            pg.draw.rect(screen, (170,0,0), pg.Rect(WIDTH - 935, HEIGHT - 160, 50, 50))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 935, HEIGHT - 160, 50, 50), 1)
            if left_pressed and mouse_position[0] >= WIDTH - 880 and mouse_position[0] <= WIDTH - 820 and mouse_position[1] >= HEIGHT - 630 and mouse_position[1] <= HEIGHT - 570:
                players[turn].attack = 4
                players[turn].subattack = 0
        if players[turn].subattack < 8:
            if left_pressed and mouse_position[0] >= WIDTH - 300 and mouse_position[0] <= WIDTH - 270 and mouse_position[1] >= HEIGHT - 590 and mouse_position[1] <= HEIGHT - 560:
                players[turn].attack = attack
                players[turn].subattack = subattack
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 950, HEIGHT - 630, 60, 60), 2)
            pg.draw.rect(screen, (170,230,170), pg.Rect(WIDTH - 900, HEIGHT - 600, 640, 560))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 900, HEIGHT - 600, 640, 560),3)
            pg.draw.rect(screen, (255,120,120), pg.Rect(WIDTH - 300, HEIGHT - 590, 30, 30))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 300, HEIGHT - 590, 30, 30), 3)
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 870, HEIGHT - 570, 130, 235), 3)   #bridge
            pg.draw.rect(screen, card_background, pg.Rect(WIDTH - 870, HEIGHT - 570, 130, 235))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 720, HEIGHT - 570, 130, 235), 3)   #rails
            pg.draw.rect(screen, card_background, pg.Rect(WIDTH - 720, HEIGHT - 570, 130, 235))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 570, HEIGHT - 570, 130, 235), 3)   #nuke
            pg.draw.rect(screen, card_background, pg.Rect(WIDTH - 570, HEIGHT - 570, 130, 235))
            if players[turn].wood >= 10 and left_pressed and mouse_position[0] >= WIDTH - 870 and mouse_position[0] <= WIDTH - 740 and mouse_position[1] >= HEIGHT - 570 and mouse_position[1] <= HEIGHT - 335:
                if players[turn].subattack == 1:
                    players[turn].subattack = 0
                else:
                    players[turn].subattack = 1
            elif players[turn].wood >= 2 and players[turn].steel >= 1 and left_pressed and mouse_position[0] >= WIDTH - 720 and mouse_position[0] <= WIDTH - 590 and mouse_position[1] >= HEIGHT - 570 and mouse_position[1] <= HEIGHT - 335:
                if players[turn].subattack == 2:
                    players[turn].subattack = 0
                else:
                    players[turn].subattack = 2
            elif players[turn].nuclear >= 5 and left_pressed and mouse_position[0] >= WIDTH - 570 and mouse_position[0] <= WIDTH - 440 and mouse_position[1] >= HEIGHT - 570 and mouse_position[1] <= HEIGHT - 335:
                if players[turn].subattack == 3:
                    players[turn].subattack = 0
                else:
                    players[turn].subattack = 3
            if players[turn].subattack == 1:
                pg.draw.rect(screen, card_selected, pg.Rect(WIDTH - 870, HEIGHT - 570, 130, 235))
            elif players[turn].subattack == 2:
                pg.draw.rect(screen, card_selected, pg.Rect(WIDTH - 720, HEIGHT - 570, 130, 235))
            elif players[turn].subattack == 3:
                pg.draw.rect(screen, card_selected, pg.Rect(WIDTH - 570, HEIGHT - 570, 130, 235))
            if attack == 0 or attack == 4:
                if players[turn].wood >= 15 and left_pressed and mouse_position[0] >= WIDTH - 870 and mouse_position[0] <= WIDTH - 740 and mouse_position[1] >= HEIGHT - 305 and mouse_position[1] <= HEIGHT - 70:
                    if players[turn].subattack == 4:
                        players[turn].subattack = 0
                    else:
                        players[turn].subattack = 4
                elif players[turn].steel >= 10 and left_pressed and mouse_position[0] >= WIDTH - 720 and mouse_position[0] <= WIDTH - 590 and mouse_position[1] >= HEIGHT - 305 and mouse_position[1] <= HEIGHT - 70:
                    if players[turn].subattack == 5:
                        players[turn].subattack = 0
                    else:
                        players[turn].subattack = 5
                elif players[turn].steel >= 20 and left_pressed and mouse_position[0] >= WIDTH - 570 and mouse_position[0] <= WIDTH - 440 and mouse_position[1] >= HEIGHT - 305 and mouse_position[1] <= HEIGHT - 70:
                    if players[turn].subattack == 6:
                        players[turn].subattack = 0
                    else:
                        players[turn].subattack = 6
                elif players[turn].wood >= 10 and left_pressed and mouse_position[0] >= WIDTH - 420 and mouse_position[0] <= WIDTH - 290 and mouse_position[1] >= HEIGHT - 305 and mouse_position[1] <= HEIGHT - 70:
                    if players[turn].subattack == 7:
                        players[turn].subattack = 0
                    else:
                        players[turn].subattack = 7
                pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 870, HEIGHT - 305, 130, 235), 3)   #ship
                pg.draw.rect(screen, card_background, pg.Rect(WIDTH - 870, HEIGHT - 305, 130, 235))
                pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 720, HEIGHT - 305, 130, 235), 3)   #plane
                pg.draw.rect(screen, card_background, pg.Rect(WIDTH - 720, HEIGHT - 305, 130, 235))
                pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 570, HEIGHT - 305, 130, 235), 3)   #tank
                pg.draw.rect(screen, card_background, pg.Rect(WIDTH - 570, HEIGHT - 305, 130, 235))
                pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 420, HEIGHT - 305, 130, 235), 3)   #fort
                pg.draw.rect(screen, card_background, pg.Rect(WIDTH - 420, HEIGHT - 305, 130, 235))
                if players[turn].subattack == 4:
                    pg.draw.rect(screen, card_selected, pg.Rect(WIDTH - 870, HEIGHT - 305, 130, 235))
                elif players[turn].subattack == 5:
                    pg.draw.rect(screen, card_selected, pg.Rect(WIDTH - 720, HEIGHT - 305, 130, 235))
                elif players[turn].subattack == 6:
                    pg.draw.rect(screen, card_selected, pg.Rect(WIDTH - 570, HEIGHT - 305, 130, 235))
                elif players[turn].subattack == 7:
                    pg.draw.rect(screen, card_selected, pg.Rect(WIDTH - 420, HEIGHT - 305, 130, 235))
                screen.blit(spr_ship, (WIDTH - 865, HEIGHT - 300))
                screen.blit(myfont.render("X 15 ", False, (0, 0, 0)), (WIDTH - 795, HEIGHT - 140))
                screen.blit(spr_wood, (WIDTH - 835, HEIGHT - 140))
                screen.blit(spr_plane, (WIDTH - 715, HEIGHT - 300))
                screen.blit(myfont.render("X 10 ", False, (0, 0, 0)), (WIDTH - 645, HEIGHT - 140))
                screen.blit(spr_steel, (WIDTH - 685, HEIGHT - 140))
                screen.blit(spr_tank, (WIDTH - 565, HEIGHT - 300))
                screen.blit(myfont.render("X 20 ", False, (0, 0, 0)), (WIDTH - 495, HEIGHT - 140))
                screen.blit(spr_steel, (WIDTH - 535, HEIGHT - 140))
                screen.blit(spr_fort, (WIDTH - 415, HEIGHT - 300))
                screen.blit(myfont.render("X 10/15/20 ", False, (0, 0, 0)), (WIDTH - 400, HEIGHT - 120))
                screen.blit(spr_wood, (WIDTH - 390, HEIGHT - 170))
            screen.blit(spr_bridge, (WIDTH - 865, HEIGHT - 565))
            screen.blit(myfont.render("X 10 ", False, (0, 0, 0)), (WIDTH - 795, HEIGHT - 405))
            screen.blit(spr_wood, (WIDTH - 835, HEIGHT - 405))
            screen.blit(spr_rails, (WIDTH - 715, HEIGHT - 565))
            screen.blit(myfont.render("X 2 ", False, (0, 0, 0)), (WIDTH - 645, HEIGHT - 435))
            screen.blit(spr_wood, (WIDTH - 685, HEIGHT - 435))
            screen.blit(myfont.render("X 1 ", False, (0, 0, 0)), (WIDTH - 645, HEIGHT - 385))
            screen.blit(spr_steel, (WIDTH - 685, HEIGHT - 385))
            screen.blit(spr_nuke, (WIDTH - 565, HEIGHT - 565))
            screen.blit(myfont.render("X 5 ", False, (0, 0, 0)), (WIDTH - 495, HEIGHT - 405))
            screen.blit(spr_nuclear, (WIDTH - 535, HEIGHT - 405))
        if players[turn].subattack > 0 and players[turn].subattack < 8:
            pg.draw.rect(screen, (100,100,255), pg.Rect(WIDTH - 935, HEIGHT - 85, 120, 60))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 935, HEIGHT - 85, 120, 60), 3)
            if left_pressed and mouse_position[0] >= WIDTH - 935 and mouse_position[0] <= WIDTH - 815 and mouse_position[1] >= HEIGHT - 85 and mouse_position[1] <= HEIGHT - 25:
                players[turn].subattack += 8
        elif players[turn].subattack == 9:   #building bridge
            if left_pressed and countries[hover_country].owner == players[turn]:
                origin_country = hover_country
                players[turn].subattack = 16
        elif players[turn].subattack == 16:
            if left_pressed and hover_country == origin_country:
                players[turn].subattack = 9
            elif left_pressed:
                for i in range(len(connections)):
                    if (hover_country, origin_country) == connections[i].connection or (origin_country, hover_country) == connections[i].connection and connections[i].kind == "sea":
                        connections[i].kind = "land"
                        players[turn].wood -= 10
                        players[turn].attack = attack
                        players[turn].subattack = subattack
                        break
        elif players[turn].subattack == 10:   #building rails
            if left_pressed and countries[hover_country].owner == players[turn]:
                origin_country = hover_country
                players[turn].subattack = 17
        elif players[turn].subattack == 17:
            if left_pressed and hover_country == origin_country:
                players[turn].subattack = 10
            elif left_pressed and countries[hover_country].owner == players[turn]:
                for i in range(len(connections)):
                    if connections[i].connection == (origin_country,hover_country) or connections[i].connection == (hover_country,origin_country) and connections[i].kind == "land":
                        connections[i].rails = True
                        players[turn].wood -= 2
                        players[turn].steel -= 1
                        players[turn].attack = attack
                        players[turn].subattack = subattack
                        break
        elif players[turn].subattack == 11:   #building nuke
            if left_pressed and countries[hover_country].owner == players[turn]:
                origin_country = hover_country
                players[turn].subattack = 18
        elif players[turn].subattack == 18:
            if left_pressed and hover_country == origin_country:
                players[turn].subattack = 11
            elif left_pressed and countries[hover_country].owner != players[turn] and np.any([origin_country in connection and hover_country in connection for connection in connections]):
                countries[hover_country].radioactive += 3
                countries[hover_country].units = int(np.round(countries[hover_country].units/2))
                if countries[hover_country].units == 0 and countries[hover_country].owner == default_player:
                    countries[hover_country].units = 2
                players[turn].nuclear -= 5
                players[turn].attack = attack
                players[turn].subattack = subattack
                
        elif players[turn].subattack == 12:   #building ship
            if left_pressed and countries[hover_country].owner == players[turn]:
                countries[hover_country].ships += 1
                players[turn].wood -= 15
                players[turn].attack = attack
                players[turn].subattack = subattack
        elif players[turn].subattack == 13:   #building plane
            if left_pressed and countries[hover_country].owner == players[turn]:
                countries[hover_country].planes += 1
                players[turn].steel -= 10
                players[turn].attack = attack
                players[turn].subattack = subattack
        elif players[turn].subattack == 14:   #building tank
            if left_pressed and countries[hover_country].owner == players[turn]:
                countries[hover_country].tanks += 1
                players[turn].steel -= 20
                players[turn].attack = attack
                players[turn].subattack = subattack
        elif players[turn].subattack == 15:   #building fort
            if left_pressed and countries[hover_country].owner == players[turn] and countries[hover_country].fort_lvl <= 2 and players[turn].wood >= 10 + 5*countries[hover_country].fort_lvl:
                players[turn].wood -= 10 + 5*countries[hover_country].fort_lvl
                countries[hover_country].fort_lvl += 1
                players[turn].attack = attack
                players[turn].subattack = subattack
        if players[turn].subattack > 8:
            pg.draw.rect(screen, (250,100,100), pg.Rect(WIDTH - 935, HEIGHT - 155, 120, 60))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 935, HEIGHT - 155, 120, 60), 3)
            if left_pressed and mouse_position[0] >= WIDTH - 935 and mouse_position[0] <= WIDTH - 815 and mouse_position[1] >= HEIGHT - 155 and mouse_position[1] <= HEIGHT - 95:
                players[turn].attack = attack
                players[turn].subattack = subattack

    elif players[turn].attack == 4:   #cards menu
        if players[turn].subattack == 0:
            pg.draw.rect(screen, (230,170,170), pg.Rect(WIDTH - 880, HEIGHT - 630, 60, 60))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 880, HEIGHT - 630, 60, 60), 2)
            screen.blit(spr_cards, (WIDTH - 875, HEIGHT - 626))
            if attack == 0:
                pg.draw.rect(screen, (0,170,0), pg.Rect(WIDTH - 935, HEIGHT - 270, 50, 50))
                pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 935, HEIGHT - 270, 50, 50), 3)
                screen.blit(myfont.render("+ "+str(reinforcements), False, (0, 0, 0)), (WIDTH - 920, HEIGHT - 200))
                pg.draw.rect(screen, (170,0,0), pg.Rect(WIDTH - 935, HEIGHT - 160, 50, 50))
                pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 935, HEIGHT - 160, 50, 50), 1)
            if left_pressed and mouse_position[0] >= WIDTH - 300 and mouse_position[0] <= WIDTH - 270 and mouse_position[1] >= HEIGHT - 590 and mouse_position[1] <= HEIGHT - 560:
                players[turn].attack = attack
                players[turn].subattack = subattack
            pg.draw.rect(screen, (230,170,170), pg.Rect(WIDTH - 900, HEIGHT - 600, 640, 340))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 900, HEIGHT - 600, 640, 340),3)
            pg.draw.rect(screen, (255,120,120), pg.Rect(WIDTH - 300, HEIGHT - 590, 30, 30))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 300, HEIGHT - 590, 30, 30), 3)
            if warning:
                screen.blit(myfont.render("WARNING", False, (0, 0, 0)), (WIDTH - 622, HEIGHT - 585))
                screen.blit(myfont.render("You currently have too many cards", False, (0, 0, 0)), (WIDTH - 720, HEIGHT - 565))
            for i in range(len(players[turn].cards)):
                pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 876 + i*76, HEIGHT - 522, 67, 136), 4)
                pg.draw.rect(screen, (250,250,250), pg.Rect(WIDTH - 876 + i*76, HEIGHT - 522, 67, 136))
                if players[turn].cards[i] == 0:
                    screen.blit(spr_card0, (WIDTH - 860 + i*76, HEIGHT - 490))
                elif players[turn].cards[i] == 1:
                    screen.blit(spr_card1, (WIDTH - 860 + i*76, HEIGHT - 490))
                elif players[turn].cards[i] == 2:
                    screen.blit(spr_card2, (WIDTH - 860 + i*76, HEIGHT - 490))
                elif players[turn].cards[i] == 3:
                    screen.blit(spr_card0, (WIDTH - 860 + i*76, HEIGHT - 515))
                    screen.blit(spr_card1, (WIDTH - 860 + i*76, HEIGHT - 472))
                    screen.blit(spr_card2, (WIDTH - 860 + i*76, HEIGHT - 420))
                if mouse_position[0] <= WIDTH - 876 + i*76 or mouse_position[0] >= WIDTH - 800 + i*76 or mouse_position[1] <= HEIGHT - 522 or mouse_position[1] >= HEIGHT - 386:
                    pg.draw.rect(screen, (150,150,150), pg.Rect(WIDTH - 876 + i*76, HEIGHT - 522, 67, 136))
            if (attack == 0 and len(players[turn].cards) >= 3) or warning:
                if set(players[turn].cards) in [{0,1,2,3}, {0,1,2}, {0,1,3}, {0,2,3}, {1,2,3}, {0,3}, {1,3}, {2,3}, {3}] and players[turn].cards.count(3) >= 3 - len(set(players[turn].cards) & {0,1,2}):
                    reward = 10
                    jokers = 3 - len(set(players[turn].cards) & {0,1,2})
                else:
                    for j in range(4):
                        for i in range(3):
                                if players[turn].cards.count(i) >= 3 - j:
                                    reward = 4 + 2*i
                                    jokers = j
                        break
            if reward in [10,8,6,4]:
                pg.draw.rect(screen, (50,240,50), pg.Rect(WIDTH - 640, HEIGHT - 340, 120, 60))
                pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 640, HEIGHT - 340, 120, 60),3)
                screen.blit(myfont.render("Exchange", False, (0, 0, 0)), (WIDTH - 621, HEIGHT - 325))
                if left_pressed and mouse_position[0] <= WIDTH - 520 and mouse_position[0] >= WIDTH - 640 and mouse_position[1] <= HEIGHT - 280 and mouse_position[1] >= HEIGHT - 340:
                    highlight = -1
                    players[turn].subattack = 1
        if players[turn].subattack == 1:
            pg.draw.rect(screen, (230,170,170), pg.Rect(WIDTH - 900, HEIGHT - 600, 640, 560))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 900, HEIGHT - 600, 640, 560),3)
            pg.draw.rect(screen, (255,120,120), pg.Rect(WIDTH - 300, HEIGHT - 590, 30, 30))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 300, HEIGHT - 590, 30, 30), 3)
            if left_pressed and mouse_position[0] >= WIDTH - 300 and mouse_position[0] <= WIDTH - 270 and mouse_position[1] >= HEIGHT - 590 and mouse_position[1] <= HEIGHT - 560:
                players[turn].attack = attack
                players[turn].subattack = subattack
            for i in range(6):
                pg.draw.rect(screen, card_background, pg.Rect(WIDTH - 810, HEIGHT - 550 + 80*i, 400, 70))
                pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 810, HEIGHT - 550 + 80*i, 400, 70),3)
                if left_pressed and mouse_position[0] >= WIDTH - 810 and mouse_position[0] <= WIDTH - 410 and mouse_position[1] >= HEIGHT - 550 + 80*i and mouse_position[1] <= HEIGHT - 480 + 80*i:
                    if highlight == i:
                        highlight = -1
                    else:
                        highlight = i
            if highlight != -1:
                pg.draw.rect(screen, card_selected, pg.Rect(WIDTH - 810, HEIGHT - 550 + 80*highlight, 400, 70))
                pg.draw.rect(screen, green_button, pg.Rect(WIDTH - 500, HEIGHT - 535 + 80*highlight, 80, 40))
                pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 500, HEIGHT - 535 + 80*highlight, 80, 40),1)
                if left_pressed and mouse_position[0] >= WIDTH - 500 and mouse_position[0] <= WIDTH - 420 and mouse_position[1] >= HEIGHT - 535 + 80*highlight and mouse_position[1] <= HEIGHT - 495 + 80*highlight:
                    if highlight == 0:
                        reinforcements += int(reward*1.5)
                        if warning and players[turn].attack != 0:
                            all_reinforcements_deployed = False
                            attack = 0
                            subattack = 1
                    elif highlight == 1:
                        players[turn].food += int(reward*3)
                    elif highlight == 2:
                        players[turn].wood += int(reward*2.5)
                    elif highlight == 3:
                        players[turn].steel += int(reward*2)
                    elif highlight == 4:
                        players[turn].oil += int(reward*2)
                    elif highlight == 5:
                        players[turn].nuclear += int(reward)
                    if reward == 10:
                        for i in range(3-jokers):
                            players[turn].cards.remove(i)
                    elif reward == 8:
                        for i in range(3-jokers):
                            players[turn].cards.remove(2)
                    elif reward == 6:
                        for i in range(3-jokers):
                            players[turn].cards.remove(1)
                    elif reward == 4:
                        for i in range(3-jokers):
                            players[turn].cards.remove(0)
                    for i in range(jokers):
                        players[turn].cards.remove(3)
                    reward = 0
                    warning = False
                        
                    players[turn].subattack = subattack
                    players[turn].attack = attack
            screen.blit(myfont.render(str(int(reward*1.5))+" X", False, (0, 0, 0)), (WIDTH - 720, HEIGHT - 520))
            screen.blit(myfont.render(str(int(reward*3))+" X", False, (0, 0, 0)), (WIDTH - 720, HEIGHT - 520 + 80))
            screen.blit(myfont.render(str(int(reward*2.5))+" X", False, (0, 0, 0)), (WIDTH - 720, HEIGHT - 520 + 80*2))
            screen.blit(myfont.render(str(int(reward*2))+" X", False, (0, 0, 0)), (WIDTH - 720, HEIGHT - 520 + 80*3))
            screen.blit(myfont.render(str(int(reward*2))+" X", False, (0, 0, 0)), (WIDTH - 720, HEIGHT - 520 + 80*4))
            screen.blit(myfont.render(str(int(reward))+" X", False, (0, 0, 0)), (WIDTH - 720, HEIGHT - 520 + 80*5))
            screen.blit(spr_troops, (WIDTH - 660, HEIGHT - 510))
            screen.blit(spr_food, (WIDTH - 660, HEIGHT - 510 + 80))
            screen.blit(spr_wood, (WIDTH - 660, HEIGHT - 510 + 80*2))
            screen.blit(spr_steel, (WIDTH - 660, HEIGHT - 510 + 80*3))
            screen.blit(spr_oil, (WIDTH - 660, HEIGHT - 510 + 80*4))
            screen.blit(spr_nuclear, (WIDTH - 660, HEIGHT - 510 + 80*5))

    elif players[turn].attack == 6:   #start_ship placement
        if players[turn].subattack == 0:
            pg.draw.rect(screen, (230,170,170), pg.Rect(WIDTH - 800, HEIGHT - 460, 440, 240))
            screen.blit(myfont.render("You have 1 ship in storage.", False, (0, 0, 0)), (WIDTH - 690, HEIGHT - 410))
            screen.blit(myfont.render("Deploy ship?", False, (0, 0, 0)), (WIDTH - 640, HEIGHT - 350))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 800, HEIGHT - 460, 440, 240),3)
            pg.draw.rect(screen, (170,0,0), pg.Rect(WIDTH - 670, HEIGHT - 290, 75, 50))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 670, HEIGHT - 290, 75, 50), 2)
            pg.draw.rect(screen, (0,170,0), pg.Rect(WIDTH - 565, HEIGHT - 290, 75, 50))
            pg.draw.rect(screen, (0,0,0), pg.Rect(WIDTH - 565, HEIGHT - 290, 75, 50), 2)
            if left_pressed and mouse_position[0] >= WIDTH - 670 and mouse_position[0] <= WIDTH - 595 and mouse_position[1] >= HEIGHT - 290 and mouse_position[1] <= HEIGHT - 240:
                checked = True
                if turn_num < player_num:
                    players[turn].attack = 1
                else:
                    players[turn].attack = 0
            elif left_pressed and mouse_position[0] >= WIDTH - 565 and mouse_position[0] <= WIDTH - 490 and mouse_position[1] >= HEIGHT - 290 and mouse_position[1] <= HEIGHT - 240:
                players[turn].subattack = 1
        if players[turn].subattack == 1:
            if left_pressed and not hover_country == -1 and countries[hover_country].owner == players[turn]:
                countries[hover_country].ships += 1
                players[turn].start_ship = False
                if turn_num < player_num:
                    players[turn].subattack = 0
                    players[turn].attack = 1
                else:
                    players[turn].subattack = 1
                    players[turn].attack = 0

    elif (players[turn].attack  == 0 and players[turn].subattack == 1 or players[turn].attack == 1) and len(players[turn].cards) >= 5:   #WARNING
        attack = players[turn].attack
        subattack = players[turn].subattack
        players[turn].attack = 4
        players[turn].subattack = 0
        warning = True

    if players[turn].attack != 6 and mouse_position[0] >= WIDTH - 200 + 70*min(players[turn].attack + 1, 2) and mouse_position[0] <= WIDTH - 200 + 70*min(players[turn].attack + 1, 2) + 60 and mouse_position[1] >= HEIGHT - 50 and mouse_position[1] <= HEIGHT - 10 and left_pressed and all_reinforcements_deployed:
        players[turn].attack = (players[turn].attack + 1) % 3
        players[turn].subattack = 0
        if players[turn].attack == 0:
            turn = (turn + 1) % player_num
            turn_num += 1
            checked = False
            
    pg.display.flip()

pg.quit()

