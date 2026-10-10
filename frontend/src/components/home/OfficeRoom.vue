<template>
  <img class="office-room" src="/assets/office/office.png" alt="" draggable="false" />
</template>

<style scoped>
/* workbzw/ai-office-react OfficeScene.drawMap 的 cover 布景，改为原生图片层。 */
.office-room {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  user-select: none;
}
</style>
