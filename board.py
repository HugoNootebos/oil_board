def countries():
    countries = [i for i in range(42)]
    countries[0] = Country("Redneck", [[(111, 150),(110, 169),(112, 187),(112, 201),(117, 207),(120, 207),(124, 212),(128, 207),(141, 205),(145, 207),(145, 204),(151, 203),(153, 192),(158, 182),(164, 174),(163, 165),(159, 164),(159, 170),(156, 173),(153, 170),(161, 159),(157, 156),(153, 159),(149, 157),(151, 152)]]
                                    , troops = 3
                                    , units = 1)
    countries[1] = Country("Madagaskar", [[(365, 396), (358, 422), (365, 424), (377, 398), (376, 388)]]
                                       , food = 1
                                       , troops = 1
                                       , wood = 2)
    countries[2] = Country ("Zuid-Afrika", [[(298, 365),(342, 365),(342, 354),(356, 354),(350, 370),(352, 394),(349, 401),(340, 407),(338, 420),(334, 424),(333, 433),(323, 450),(305, 454),(300, 452),(303, 442),(298, 430),(297, 415),(292, 400),(297, 388),(297, 372)]]
                                         , food = 1
                                         , troops = 2
                                         , units = 1)
    countries[3] = Country("Belgisch Congo", [[(288, 351),(303, 351),(303, 320),(322, 320),(342, 320),(342, 354),(342, 365),(298, 365)]]
                                           , troops = 3
                                           , steel = 1)
    countries[4] = Country("Somalië", [[(356, 354),(342, 354),(342, 320),(322, 320),(322, 299),(358, 299),(365, 310),(362, 312),(369, 314),(382, 310),(380, 314),(379, 321),(368, 341)]]
                                    , troops = 3
                                    , wood = 1)
    countries[5] = Country("Nigeria", [[(238, 299),(322, 299),(322, 320),(303, 320),(303, 351),(288, 351),(292, 346),(293, 333),(279, 327),(255, 331)]]
                                    , troops = 3
                                    , wood = 1)
    countries[6] = Country("Sahara", [[(298, 234),(307, 237),(309, 243),(315, 243),(319, 236),(335, 243),(345, 245),(345, 251),(350, 266),(355, 281),(358, 299),(322, 299),(238, 299),(243, 286),(240, 272),(247, 268),(245, 261),(256, 250),(258, 238),(267, 228),(298, 223)]]
                                   , troops = 2
                                   , oil = 1
                                   , nuclear = 1)
    countries[7] = Country("IJsland", [[(280, 103), (271, 103), (260, 103), (262, 112), (270, 113), (281, 108)]]
                                    , troops = 1
                                    , wood = 2
                                    , oil = 1)
    countries[8] = Country("Viking", [[(331, 119),(339, 109),(337, 94),(335, 80),(340, 70),(336, 69),(338, 64),(334, 62),(323, 63),(304, 81),(299, 97),(287, 113),(288, 126),(294, 130),(298, 125),(303, 138),(301, 144),(306, 143),(309, 137),(314, 121),(312, 110),(321, 94),(326, 93),(326, 99),(321, 107),(320, 120)]]
                                   , food = 2
                                   , wood = 1
                                   , oil = 1)
    countries[9] = Country("Sovjet-Rusland", [[(344, 181),(345, 188),(352, 187),(350, 182),(359, 179),(356, 186),(356, 191),(361, 191),(364, 200),(378, 210),(381, 205),(376, 200),(375, 186),(370, 164),(377, 155),(402, 155),(406, 153),(407, 149),(406, 142),(404, 123),(402, 95),(408, 86),(410, 76),(398, 71),(399, 77),
                                              (389, 77),(371, 87),(370, 80),(365, 80),(367, 90),(360, 101),(350, 100),(352, 95),(344, 90),(344, 86),(348, 88),(360, 86),(359, 79),(344, 67),(340, 70),(335, 80),(337, 94),(339, 109),(331, 119),(336, 124),(348, 127),(358, 138),(359, 158),(355, 172),(332, 182),(337, 187)]]
                                           , troops = 3
                                           , wood = 1
                                           , oil = 1)
    countries[10] = Country("Belarus", [[(322, 133),(326, 135),(325, 126),(336, 124),(348, 127),(358, 138),(359, 158),(355, 172),(332, 182),(319, 175),(323, 160),(320, 147)]]
                                         , food = 4
                                         , wood = 1)
    countries[11] = Country("Nazi-Duitsland", [[(274, 179),(270, 175),(282, 169),(291, 153),(295, 149),(293, 138),(297, 133),(299, 139),(298, 147),(307, 149),(320, 147),(323, 160),(319, 175),(306, 174),(300, 177),(293, 177),(290, 185),(277, 189)]]
                                            , food = 1
                                            , troops = 1
                                            , steel = 2)
    countries[12] = Country("Romeinse Rijk", [[(334, 196),(330, 200),(329, 208),(325, 208),(327, 216),(323, 223),(318, 203),(306, 187),(305, 195),(313, 202),(318, 211),(313, 209),(315, 215),(310, 219),(310, 211),(297, 191),(291, 196),(290, 185),(293, 177),(300, 177),(306, 174),(319, 175),(332, 182),(337, 187)]]
                                    , food = 4)
    countries[13] = Country("Spanje", [[(280, 203),(281, 216),(268, 224),(259, 222),(258, 197),(261, 194),(271, 194),(277, 189),(290, 185),(291, 196),(284, 197)]]
                                            , food = 2
                                            , troops = 1
                                            , units = 1)
    countries[14] = Country("Londen", [[(271, 131),(270, 143),(273, 141),(274, 153),(270, 153),(269, 161),(273, 161),(265, 168),(266, 170),(282, 164),(285, 157),(281, 157),(283, 154),(279, 146),(277, 140),(281, 135),(278, 133),(275, 134),(278, 127)],[(262, 145),(260, 156),(259, 163),(267, 158),(267, 152),(270, 148),(267, 144)]]
                                    , food = 2
                                    , wood = 1
                                    , units = 1)
    countries[15] = Country("Siberië", [[(410, 137),(410, 104),(408, 99),(409, 93),(414, 87),(413, 77),(415, 68),(423, 74),(419, 80),(424, 86),(424, 96),(418, 101),(427, 98),(428, 90),(431, 95),(435, 92),(431, 86),(427, 85),(425, 77),(427, 73),(433, 79),(436, 80),(441, 82),(439, 72),(435, 68),(439, 65),(441, 67),(457, 56),
                                         (467, 56),(467, 52),(473, 49),(479, 56),(488, 54),(489, 60),(475, 70),(488, 66),(508, 68),(507, 64),(520, 65),(519, 70),(526, 73),(539, 71),(535, 66),(567, 72),(572, 75),(576, 75),(578, 78),(596, 79),(593, 74),(613, 78),(623, 87),(631, 90),(628, 95),(627, 98),(622, 98),(622, 94),(614, 89),(613, 95),(607, 96),(614, 103),
                                         (612, 106),(609, 104),(600, 114),(593, 112),(586, 120),(589, 126),(588, 134),(585, 133),(585, 145),(581, 146),(577, 140),(575, 126),(587, 112),(588, 108),(591, 105),(585, 105),(581, 113),(579, 108),(573, 109),(573, 119),(568, 120),(563, 117),(549, 118),(539, 133),(546, 137),(547, 134),(552, 140),(554, 151),(553, 164),
                                         (540, 157),(522, 165),(519, 156),(489, 149),(459, 149),(435, 155),(426, 143),(413, 140)]]
                                     , food = 1
                                     , steel = 1
                                     , oil = 1
                                     , units = 1)
    countries[16] = Country("Kazachstan", [[(392, 219),(400, 217),(405, 227),(422, 218),(441, 221),(432, 215),(429, 198),(437, 194),(449, 173),(435, 155),(426, 143),(413, 140),(414, 154),(406, 161),(389, 160),(380, 162),(376, 170),(379, 175),(379, 183),(382, 180),(388, 181),(388, 188),(385, 186),(384, 194),(387, 196),(388, 202),(390, 197),
                                          (391, 203),(389, 205),(388, 211),(391, 213)]]
                                        , food = 1
                                        , troops = 1
                                        , oil = 1
                                        , nuclear = 1)
    countries[17] = Country("China", [[(518, 197),(513, 182),(504, 190),(460, 179),(449, 173),(437, 194),(429, 198),(432, 215),(441, 221),(441, 235),(462, 250),(471, 247),(477, 237),(481, 241),(485, 241),(484, 254),(489, 254),(495, 246),(499, 252),(507, 251),(509, 253),(520, 244),(526, 236),(530, 221),(523, 208),(530, 203),(521, 204)]]
                                   , food = 8
                                   , units = 3)
    countries[18] = Country("Mongolië", [[(522, 165),(519, 156),(489, 149),(459, 149),(435, 155),     (449, 173),(460, 179),(504, 190),(513, 182)]]
                                      , food = 1
                                      , troops = 1
                                      , steel = 1
                                      , units = 1)
    countries[19] = Country("Noord-Korea", [[(553, 164),(540, 157),(522, 165),(513, 182),(518, 197),(526, 190),(528, 196),(533, 194),(539, 206),(546, 200),(537, 189),(545, 179)]]
                                         , troops = 2
                                         , units = 1)
    countries[20] = Country("Maleisië", [[(472, 267),(478, 257),(481, 241),(485, 241),(484, 254),(489, 254),(495, 246),(499, 252),(495, 262),(501, 269),(501, 280),(493, 289),(491, 282),(484, 276),(481, 284),(483, 290),(490, 296),(490, 308),(483, 303),(482, 295),(478, 290),(478, 275)]]
                                      , food = 1
                                      , wood = 2
                                      , units = 1)
    countries[21] = Country("Sri Lanka", [[(442, 320), (442, 328), (450, 327), (450, 319), (445, 314)]]
                                       , food = 1
                                       , troops = 1
                                       , wood = 2)
    countries[22] = Country("India", [[(408, 262),(407, 245),(405, 227),(422, 218),(441, 221),(441, 235),(462, 250),(471, 247),(477, 237),(481, 241),(478, 257),(472, 267),(458, 271),(451, 284),(446, 302),(441, 313),(440, 319),(435, 315),(430, 297),(428, 274),(416, 262)]]
                                   , food = 1
                                   , troops = 1
                                   , wood = 1
                                   , units = 1)
    countries[23] = Country("Ottomaanse Rijk", [[(401, 263),(399, 258),(393, 261),(386, 256),(383, 246),(376, 249),(365, 242),(353, 240),(351, 223),(332, 224),(330, 216),(330, 210),(335, 199),(337, 203),(343, 200),(354, 200),(354, 204),(360, 204),(364, 205),(370, 213),(374, 216),(378, 215),(379, 220),(386, 221),(392, 219),
                                                 (400, 217),(405, 227),(407, 245),(408, 262)]]
                                             , food = 2
                                             , troops = 1
                                             , oil = 1)
    countries[24] = Country("Arabië", [[(353, 240),(365, 242),(376, 249),(384, 263),(387, 261),(386, 266),(387, 269),(397, 263),(403, 274),(398, 286),(395, 285),(394, 292),(369, 306),(362, 284),(357, 277),(357, 270),(348, 243)]]
                                    , oil = 5)
    countries[25] = Country("Japan", [[(563, 187),(561, 193),(554, 197),(549, 205),(559, 199),(568, 198),(568, 189),(566, 176)],[(546, 209), (548, 217), (552, 213), (551, 208)],[(555, 208), (560, 202), (553, 206)],[(561, 173), (568, 174), (571, 170), (566, 166)],[(566, 152), (561, 146), (556, 135), (556, 148), (562, 165)],
                                      [(539, 271), (552, 280), (552, 274), (545, 267), (548, 262), (542, 255)],[(542, 277), (544, 289), (547, 280)]]
                                   , food = 1
                                   , wood = 1
                                   , steel = 1
                                   , units = 1)
    countries[26] = Country("Nederlands-Indië", [[(521, 345), (529, 341), (514, 341)],[(471, 309),(481, 332),(490, 343),(508, 345),(511, 340),(495, 337),(480, 313)],
                                                 [(505, 313),(513, 302),(517, 306),(514, 319),(507, 331),(497, 329),(497, 318)],[(520, 322), (520, 331), (512, 334), (518, 318), (529, 317)]]
                                              , food = 1
                                              , wood = 2
                                              , steel = 1)
    countries[27] = Country("Outback", [[(534, 367),(537, 361),(528, 358),(519, 364),(520, 367),(516, 368),(515, 364),(508, 368),(503, 376),(487, 384),(487, 388),(483, 386),(484, 399),(481, 398),(486, 418),(484, 421),(489, 426),(504, 418),(509, 421),(513, 414),(521, 415),(523, 411),(530, 413),(533, 420),(537, 418),(540, 414),(540, 424),(549, 421),(556, 405),(552, 392),(545, 382),(546, 372)]]
                                     , food = 1
                                     , steel = 3
                                     , nuclear = 1)
    countries[28] = Country("Gold Coast", [[(546, 372),(545, 382),(552, 392),(556, 405),(549, 421),(540, 424),(543, 431),(553, 434),(567, 429),(570, 420),(575, 413),(577, 405),(576, 394),(568, 388),(563, 379),(558, 377),(557, 366),(553, 366),(549, 357)],[(604, 399), (603, 411), (594, 423), (592, 428), (582, 419), (600, 395)],
                                           [(606, 394),(607, 401),(615, 393),(614, 385),(608, 387),(601, 376),(603, 386),(601, 391)],[(549, 439), (552, 447), (556, 446), (558, 438)]]
                                        , food = 1
                                        , troops = 1
                                        , steel = 2)
    countries[29] = Country("Papoea Nieuw Guinea", [[(573, 329),(565, 325),(562, 331),(558, 328),(560, 324),(557, 322),(553, 325),(553, 333),(561, 335),(563, 340),(570, 346),(573, 341),(587, 350),(580, 340),(581, 337)]]
                                                 , food = 1
                                                 , troops = 1
                                                 , wood = 1
                                                 , steel = 1)
    countries[30] = Country("Argentinië", [[(140, 435),(147, 453),(158, 462),(171, 464),(159, 453),(158, 444),(163, 417),(167, 418),(168, 410),(177, 410),(179, 404),(175, 396),(184, 397),(196, 381),(181, 380),(173, 374),(164, 362),(152, 358),(145, 352)]]
                                        , food = 1
                                        , steel = 2
                                        , units = 1)
    countries[31] = Country("Venezuela", [[(160, 262),(155, 263),(149, 261),(147, 263),(145, 267),(143, 263),(144, 259),(131, 263),(129, 267),(126, 268),(127, 271),(124, 272),(123, 266),(119, 274),(121, 282),(118, 295),(127, 296),(136, 303),(144, 293),(157, 285),(175, 291),(194, 284),(180, 278),(175, 277),(174, 273),(168, 273),(166, 265)]]
                                       , troops = 1
                                       , steel = 3
                                       , nuclear = 1)
    countries[32] = Country("Brazilië", [[(196, 372),(204, 364),(213, 362),(221, 351),(222, 330),(229, 325),(233, 311),(203, 297),(198, 300),(192, 300),(195, 292),(194, 284),(175, 291),(157, 285),(144, 293),(136, 303),(134, 311),(129, 316),(136, 325),(141, 321),(144, 329),(152, 323),(166, 334),(176, 351),(174, 358),(182, 363),(173, 374),(181, 380),(196, 381)]]
                                  , steel = 1
                                  , wood = 3)
    countries[33] = Country("Peru", [[(117, 308),(113, 303),(118, 295),(127, 296),(136, 303),(134, 311),(129, 316),(136, 325),(141, 321),(144, 329),(152, 323),(166, 334),(176, 351),(174, 358),(182, 363),(173, 374),(164, 362),(152, 358),(145, 352),(136, 348),(129, 343),(124, 333),(114, 315)]]
                                      , steel = 3
                                      , food = 1
                                      , troops = 1)
    countries[34] = Country("Alaska", [[(43, 70),(39, 66),(31, 69),(20, 76),(24, 83),(27, 83),(25, 87),(19, 83),(15, 91),(25, 92),(21, 98),(12, 98),(11, 107),(16, 109),(16, 115),(25, 115),(22, 120),(12, 126),(25, 122),(41, 106),(44, 106),(39, 112),(48, 110),(47, 105),(61, 115),(69, 118),(74, 131),(78, 131),(77, 122),(68, 109),(65, 75)]]
                                    , food = 1
                                    , troops = 1
                                    , steel = 1
                                    , oil = 1)
    countries[35] = Country("New York", [[(191, 163),(193, 158),(200, 158),(199, 166),(189, 172),(189, 176),(184, 177),(176, 184),(178, 189),(174, 190),(165, 197),(163, 205),(164, 214),(161, 219),(158, 218),(158, 204),(156, 204),(154, 206),(151, 203),(153, 192),(158, 182),(164, 174),(179, 167),(178, 164)]]
                                      , food = 4)
    countries[36] = Country("Californië", [[(89, 156),(85, 156),(83, 170),(85, 183),(90, 198),(98, 198),(103, 203),(112, 201),(112, 187),(110, 169),(111, 150),(86, 150)]]
                                        , food = 2
                                        , troops = 1
                                        , wood = 1)
    countries[37] = Country("Canada", [[(81, 77),(107, 74),(120, 80),(118, 82),(130, 84),(132, 80),(138, 80),(140, 82),(149, 81),(147, 76),(152, 76),(153, 80),(156, 79),(155, 74),(158, 64),(168, 57),(170, 61),(163, 65),(161, 70),(163, 76),(171, 84),(174, 80),(180, 80),(180, 88),(176, 91),(169, 91),(166, 95),(161, 92),(164, 97),(151, 107),(149, 115),(152, 124),(164, 132),(171, 132),(170, 139),
                                        (174, 144),(178, 140),(177, 133),(180, 132),(185, 127),(183, 119),(185, 117),(188, 107),(197, 107),(202, 114),(200, 116),(204, 121),(210, 117),(211, 113),(214, 112),(214, 121),(219, 132),(224, 137),(225, 142),(214, 148),(202, 149),(195, 153),(207, 153),(206, 160),(208, 162),(212, 160),(212, 163),(205, 167),(203, 171),(198, 171),(204, 165),(199, 166),
                                        (200, 158),(193, 158),(191, 163),(178, 164),(166, 170),(167, 163),(170, 165),(170, 160),(164, 158),(163, 153),(159, 150),(151, 152),(111, 150),(86, 150),(78, 131),(77, 122),(68, 109),(65, 75)],
                                        [(123, 80),(119, 74),(113, 74),(112, 69),(120, 68),(116, 62),(121, 59),(135, 67),(140, 61),(144, 74)],[(146, 65), (148, 69), (156, 64), (153, 60)],[(140, 55), (140, 49), (128, 52), (125, 47), (116, 49), (124, 56)],[(100, 63), (116, 57), (112, 54)],[(146, 49), (145, 53), (151, 54), (155, 51), (154, 47)],
                                        [(155, 40), (164, 53), (178, 55), (180, 50), (167, 50), (155, 35)],[(166, 22),(191, 25),(169, 27),(169, 31),(173, 31),(174, 38),(163, 40),(183, 46),(190, 39),(217, 23),(219, 18),(196, 15),(172, 16)],
                                        [(170, 68),(175, 76),(189, 78),(196, 91),(185, 96),(194, 98),(203, 105),(207, 103),(206, 90),(212, 95),(206, 85),(200, 72),(188, 69),(186, 62),(180, 70),(176, 69),(179, 62)],[(165, 106), (171, 102), (176, 104), (170, 96)],[(215, 155), (227, 158), (226, 146)]]
                                    , wood = 2
                                    , oil = 1
                                    , nuclear = 1)
    countries[38] = Country("Mexico", [[(94, 206),(98, 211),(98, 213),(96, 214),(98, 217),(101, 218),(102, 222),(105, 221),(98, 206),(101, 205),(108, 221),(104, 225),(105, 228),(109, 227),(112, 231),(118, 234),(126, 241),(127, 253),(131, 259),(135, 257),(131, 253),(139, 245),(139, 242),(135, 241),(143, 233),(138, 229),(135, 232),(127, 231),(123, 225),(124, 212),(120, 207),(117, 207),(112, 201),
                                        (103, 203),(98, 198),(90, 198)]]
                                    , food = 1
                                    , troops = 1
                                    , wood = 1
                                    , units = 1)
    countries[39] = Country("Groenland", [[(189, 49),(192, 56),(205, 55),(221, 75),(223, 89),(217, 97),(219, 114),(233, 127),(244, 100),(254, 100),(278, 87),(279, 77),(284, 85),(287, 82),(283, 70),(290, 71),(291, 45),(304, 31),(277, 32),(291, 26),(261, 14),(254, 14),(247, 20),(234, 27),(217, 29),(201, 38)]]
                                       , food = 2
                                       , oil = 1
                                       , units = 1)
    countries[40] = Country("Cuba", [[(169, 226),(173, 226),(179, 229),(186, 231),(190, 237),(185, 235),(174, 235),(174, 230),(169, 230),(167, 226),(162, 227),(158, 223),(168, 221)]]
                                  , food = 2
                                  , troops = 1
                                  , wood = 1)
    countries[41] = Country("Pearl Harbor", [[(30, 225),(36, 224),(39, 220),(42, 221),(43, 224),(47, 220),(43, 218),(43, 215),(35, 212)]]
                                          , troops = 2
                                      , units = 1)
    return countries

def connections():
    connections = []
    connections += [Connection((30,32),'land')]
    connections += [Connection((30,33),'land')]
    connections += [Connection((32,33),'land')]
    connections += [Connection((32,31),'land')]
    connections += [Connection((33,31),'land')]
    connections += [Connection((32,5),'sea')]
    connections += [Connection((5,3),'land')]
    connections += [Connection((3,4),'land')]
    connections += [Connection((4,5),'land')]
    connections += [Connection((5,2),'land')]
    connections += [Connection((2,1),'sea')]
    connections += [Connection((2,3),'land')]
    connections += [Connection((1,21),'sea')]
    connections += [Connection((1,4),'sea')]
    connections += [Connection((4,24),'sea')]
    connections += [Connection((4,6),'land')]
    connections += [Connection((24,6),'land')]
    connections += [Connection((24,22),'sea')]
    connections += [Connection((21,22),'sea')]
    connections += [Connection((22,16),'land')]
    connections += [Connection((16,23),'land')]
    connections += [Connection((24,23),'land')]
    connections += [Connection((23,6),'sea')]
    connections += [Connection((5,13),'sea')]
    connections += [Connection((6,13),'sea')]
    connections += [Connection((6,12),'sea')]
    connections += [Connection((11,13),'land')]
    connections += [Connection((11,12),'land')]
    connections += [Connection((10,12),'land')]
    connections += [Connection((13,14),'sea')]
    connections += [Connection((11,14),'sea')]
    connections += [Connection((14,8),'sea')]
    connections += [Connection((11,8),'sea')]
    connections += [Connection((8,7),'sea')]
    connections += [Connection((14,7),'sea')]
    connections += [Connection((12,23),'land')]
    connections += [Connection((11,10),'land')]
    connections += [Connection((23,10),'land')]
    connections += [Connection((16,18),'land')]
    connections += [Connection((16,9),'land')]
    connections += [Connection((18,9),'land')]
    connections += [Connection((9,15),'land')]
    connections += [Connection((18,17),'land')]
    connections += [Connection((22,17),'land')]
    connections += [Connection((17,19),'land')]
    connections += [Connection((17,25),'sea')]
    connections += [Connection((19,25),'sea')]
    connections += [Connection((25,15),'sea')]
    connections += [Connection((17,20),'land')]
    connections += [Connection((20,22),'sea')]
    connections += [Connection((20,26),'sea')]
    connections += [Connection((26,27),'sea')]
    connections += [Connection((27,28),'land')]
    connections += [Connection((29,28),'sea')]
    connections += [Connection((29,25),'sea')]
    connections += [Connection((34,15),'sea')]
    connections += [Connection((34,37),'land')]
    connections += [Connection((36,34),'sea')]
    connections += [Connection((36,41),'sea')]
    connections += [Connection((25,41),'sea')]
    connections += [Connection((36,0),'land')]
    connections += [Connection((37,39),'sea')]
    connections += [Connection((0,37),'land')]
    connections += [Connection((35,0),'land')]
    connections += [Connection((37,35),'sea')]
    connections += [Connection((35,14),'sea')]
    connections += [Connection((7,39),'sea')]
    connections += [Connection((35,40),'sea')]
    connections += [Connection((40,31),'sea')]
    connections += [Connection((36,38),'land')]
    connections += [Connection((36,37),'land')]
    connections += [Connection((0,38),'land')]
    connections += [Connection((38,31),'land')]
    connections += [Connection((8,9),'sea')]
    connections += [Connection((9,10),'land')]
    return connections