---
tipo: cuestionario
nombre: "Ejemplo: repaso de fracciones"
seccion: 0
intentos: ilimitados
preguntas:
  - tipo: opcion_multiple
    enunciado: ¿Qué fracción es equivalente a **1/2**?
    opciones:
      - {texto: "2/4", correcta: true, retro: Multiplica numerador y denominador por 2.}
      - {texto: "1/4", retro: "Has cambiado solo el denominador: 1/4 es la mitad de 1/2."}
      - {texto: "2/3", retro: "Has sumado 1 arriba y abajo: sumar no conserva la cantidad."}
    retro: Dos fracciones son equivalentes si representan la misma cantidad.
  - tipo: verdadero_falso
    enunciado: En la figura 1 de la descripción, el punto está coloreado.
    respuesta: verdadero
  - tipo: respuesta_corta
    enunciado: ¿Cómo se llama el número de abajo de una fracción?
    aceptadas: [denominador, el denominador]
  - tipo: numerica
    enunciado: Escribe 3/4 como número decimal.
    valor: 0.75
    tolerancia: 0.001
  - tipo: emparejamiento
    enunciado: Une cada fracción con su valor decimal.
    parejas:
      - {pregunta: "1/2", respuesta: "0,5"}
      - {pregunta: "1/4", respuesta: "0,25"}
      - {pregunta: "3/4", respuesta: "0,75"}
    distractores: ["0,3"]
    retro: Divide el numerador entre el denominador.
  - tipo: verdadero_falso
    enunciado: "La figura es un punto: ![Un punto negro sobre fondo blanco](img/punto.png)"
    respuesta: verdadero
---

Repaso de fracciones. Puedes intentarlo tantas veces como quieras.

![Figura 1](img/punto.png)
