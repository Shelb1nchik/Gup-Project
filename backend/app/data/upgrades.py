# upgrade_groups: список групп, каждая группа — список названий танков,
# которые могут улучшаться друг в друга в любом направлении.
upgrade_groups = [
    # Америка
    ["M2A4", "M2A2", "M3 Stuart", "M3A1 Stuart", "M5A1 Stuart", "M3A3 Stuart (IT)", "M3A3 Stuart (CN)", "M5A1 Stuart (CN)", "M3A3 Stuart (FR)",
     "M8 HMC", "M8 HMC (CN)", "M8A1", "Stuart I", "Stuart III"], # Стюарты
    ["M4A1", "M4", "M4A2", "M4A3 (105)", "M4A3 (76) W", "M4A3E2", "M4A3E2 (76) W", "M4/T26", "M4A2 (76) W", "M4A2 (76) W USSR", "M4A3 (76) Hell",
     "M4A3 (76) W (JP)", "Sherman II", "Sherman III/IV", "Sherman I Composito", "Sherman IC 'Trzyniec'", "Sherman Ic", "Sherman VC Firefly", "Sherman Vc (ITA)",
     "Sherman V", "M4A4 1st PTG", "M4 748(a)", "M4A4 (FR)", "M4A1 (FR)", "M4A3 (105) FR", "M4A4 (CN)", "M4A4 (SA50)", "M4A4 (FL10)", "M10 GMC",
     "M10 GMC (CN)", "M10 (FR)", "M36 (CN)", "M36", "M36B2", "M36 (JP)", "M36B1 (IT)", "M36B2 (FR)", "M4A1 (75) W", "Firefly (Overlord)", "M4A3E2 (FR)", "Achilles"], # Шерманы
    ["M26", "M26E1", "T26E1-1", "T26E5", "M46", "M26 (FR)", "M26A1", "M46 (FR)", "M47", "mKPz M47 G", "M47 (JP)", "M26 'D.C.Ariete'"], # Першинги
    ["T29", "T30", "T34"], # Т34
    ["M6A1", "T1E1", "T1E1 (90)", "M6A2E1"], # Гусыня
    ["T28", "T95"], # Черепаха
    ["M41A3 (CN)", "M41A1", "M41A1 (JP)", "leKPz M41", "M64 (CN)"], # Бульдоги
    ["M18", "M18 CN", "M18 (IT)", "M18 'Black Cat'", "Hellcat Hell", "Super Hellcat", "T86"], # Хелкаты
    ["M24 Chaffee", "M24 DK", "M24 TL", "M24 (JP)", "M24 (CN)", "M24 (IT)"], # Чафики
    ["Grant I", "Grant I (US)", "M3 Lee", "M-3 Средний", "Ram I", "Ram II", "M4A5", "QF 3.7 Ram"], # Рамы
    ["LVT(A)(4) (ZIS-2)", "LVT(A)(4) (ZIS-2) (CN)", "LVT(A)(1) (M24)", "LVT(A)(4)", "LVT(A)(1)"], #ЛВТ
    ["T20", "T25"],

    # Германия
    ["Pz.II C", "Pz.II F"], # Пазики 2
    ["Pz.III B", "Pz.III E", "Pz.III F", "Pz.III J", "Pz.III J1", "Pz.III L", "Pz.III N", "Pz.III N ITA", "Pz.III M", "StuG III F", "StuG III A",
     "StuG III G", "StuG III G(IT)", "StuH 42 G", "T-III"], # Пазики 3
    ["Pz.IV C", "Pz.IV E", "Pz.IV F1", "Pz.IV F2", "Pz.IV G", "Pz.IV G (IT)", "Pz.IV (FIN)", "Pz.IV J", "Pz.IV H", "Jagdpanzer IV", "Pz.Bef.Wg. IV J",
     "Dicker Max", "Brummbar", "Panzer IV/70 (V)", "Panzer IV/70 (A)", "Nashorn", "VFW"], # Пазики 4
    ["Tiger H1", "Tiger H1 'Ost'", "Tiger H1 'West'", "Tiger E", "Tigris", "Heavy Tank No.6", "38 cm Sturmmorser"], # Тигры 1
    ["VK 45.01 (P)", "Pz.Bef.Wg. VI P", "Ferdinand", "Elefant"], # Феди
    ["Tiger II (P)", "Tiger II (H)", "Jagdtiger", "Tiger II (H) Sla.16", "Kungstiger", "Tiger II (H) 10.5cm"], # Королевские Тигры
    ["Panther D", "Panther A", "Panther G", "Panther F", "Panther Dauphine", "Panther M10", "Jagdpanther G1", "Panther II", "VK 3002 (M)", "T-V"], # Пантеры
    ["Pz.35 (t)", "Pz.38(t) A", "Pz.38(t) F", "Pz.38(t) n.A.", "Jagdpanzer 38(t)", "Marder III", "Marder III H", "Strv m/41 S-I", "Strv m/41 S-II", "Pvkv III",
     "Pvkv II", "Sav m/43 (1944)", "Sav m/43 (1946)"], # Чехи

    # Советские танки
    ["КВ-1 (Л-11)", "КВ-1С", "КВ-1 (ЗиС-5)", "KV-1 (1942)", "KW I C 756 (r)", "КВ-85", "КВ-122", "КВ-220", "КВ-7 (У-13)", "КВ-1Э", "KV-1B",
     "КВ-2 (1939)", "КВ-2 (1940)", "КВ-2 (ЗиС-6)", "KW II 754 (r)", "СУ-152"], # КВшки
    ["Т-34 (1940)", "Т-34 (1941)", "Т-34 (1942)", "Т-34 СТЗ", "Т-34Э", "Т-34-57", "Т-34-57 (1943)", "Т-34-85 (Д-5Т)", "Т-34-85", "Т-34-85Э", "Т-34-85(45)",
     "Т-34-85 СТП", "Т-34-100", "T-34 747 (r)", "T-34 (1943) CN", "T-34 (FIN)", "T-34-85 (S-53) CN", "T-34-85 Gai", "T-34-85 (FIN)", "СУ-122", "СУ-85",
     "СУ-85М", "СУ-100", "SU-100 (CN)", "Т-34 (Прототип)", "СУ-122П"], # Т-34
    ["ИС-1", "ИС-2", "ИС-2 (1944)", "IS-2 (CN)", "IS-2 (1944) CN", "ИСУ-152", "ИСУ-122", "ИСУ-122С", "ISU-152 CN", "ISU-122 (CN)", "ИС-2 №321", "Объект 248", "ИС-1(45)"], # ИСы
    ["БТ-5", "БТ-7", "БТ-7М", "BT-42", "БТ-7А (Ф-32)"], # БТшки
    ["Т-60", "Т-70", "Т-80", "СУ-57Б", "СУ-76Д", "SU-76M (CN)", "СУ-76М", "СУ-85А"], # Т-60/T-70/T-80
    ["Т-28 (1938)", "Т-28", "Т-28Э", "T-28 (FIN)"], # Т-28
    ["Т-44ПМ", "Т-44", "Т-44-122", "Т-44-100"], # Т-44
    ["Т-26-4", "Т-26 (CN)", "Т-26", "Т-26Э", "T-26E (FIN)", "Vickers Mk.E", "СУ-5-1"], # Т-26
    ["ПТ-76Б", "PT-76", "АСУ-85", "PT-76 (CN)", "Object 211", "Type 63"], # ПТшки

    # Британия
    ["Churchill I", "Churchill AVRE", "Churchill III", "Pz.Kpfw.Churchill", "Churchill NA75", "Churchill VII", "Black Prince", "Gun Carrier", "Churchill Crocodile"], # Черчилли
    ["Valentine I", "Valentine XI", "Valentine IX", "Archer", "MK-IX 'Валентин'"], # Валентайны
    ["Matilda III", "MK-II Матильда"], # Матильды
    ["A13 Mk. I", "A13 Mk. II", "A13 Mk. II 1939"],
    ["Crusader Mk II", "Crusader Mk II (FR)", "Crusader Mk III"],
    ["Cromwell V", "Cromwell I", "Avenger", "Avenger (Overlord)", "Challenger", "Comet", "Comet (FIN)", "Charioteer Mk VII", "Charioteer Mk VII (FIN)", "Excelsior"],
    ["Centurion Mk.1", "Centurion Mk.2", "Conway"],
    ["A.C. I", "A.C. IV"],
    ["Tetrach I", "Harry Hopkins", "Alecto I"],

    # Япония
    ["Ro-Go", "Ro-Go Exp."],
    ["Ha-Go", "Ha-Go Commander"],
    ["Chi-Ha", "Chi-Ha (CN)", "Chi-Ha Short Gun", "Chi-Ha Kai", "Chi-Ha Kai (CN)", "Chi-Ha LG", "Ho-I", "Chi-He", "Ho-Ni I", "Ho-Ni II", "Ho-Ni III", "Chi-Nu", "Chi-Nu II"],
    ["Chi-To", "Chi-To Late"],
    ["Chi-Ri", "Ho-Ri Prototype", "Ho-Ri Production"],
    ["ST-A1", "ST-A2", "ST-A3", "Type 61", "Type 61 (B)"],

    # Китай
    ["Type 62", "Type 62 (CN)"],

    # Италия
    ["M13/40 (I)", "M13/40 (II)", "M13/40 (III)", "M14/41", "M15/42", "75/18 M41", "75/32 M41", "75/34 M42", "105/25 M43", "75/34 M43", "90/53 M41M", "75/46 M43", "M14/41 (47/40)"],
    ["L6/40", "47/32 L40"],
    ["Turan I", "Turan II", "Turan III", "Zrinyi I", "Zrinyi II"],

    # Франция
    ["B1 bis", "B1 ter"],
    ["ARL-44", "ARL-44 (ACL-1)"],
    ["AMX-13", "AMX-13-M24", "AMX-13 (FL11)"],
    ["AMX M4", "Foch"],
    ["CA Lorraine", "Lorraine 40t"],
    ["2C bis", "2C"],
    ["H.35", "H.39"],
    ["S.35", "Sau 40"],

    # Швеция
    ["Toldi IIa", "Strv m/38", "Strv m/40L", "Strv m/39", "Pvkv IV"],
    ["Lago 1", "Strv m/42 EH", "Strv m/42 DT", "Strv 74", "Pvkv m/43 (1946)", "Pvkv m/43 (1963)", "Ikv 73"],
    ["Ikv 72", "Ikv 103"]
]